"""
nitter/reliable_nitter.py — Reliable Nitter instance manager

Problems with plain Nitter scraping:
- Public instances go offline randomly
- Rate limits kick in without warning
- Some instances block bots
- No way to know which instance is healthy before trying

This module solves all four:
1. Health-checks all known instances before each scan
2. Ranks them by response time
3. Rotates through healthy instances per request
4. Falls back gracefully — if all Nitter fails, uses RSS feeds
5. Caches instance health so it doesn't re-check every request
"""

import asyncio
import time
import json
import re
import aiohttp
from pathlib import Path
from html.parser import HTMLParser
from core.logger import log

HEALTH_CACHE_FILE = Path(__file__).parent.parent / "data" / "nitter_health.json"
HEALTH_TTL_MIN    = 30   # re-check instance health every 30 minutes

# Complete list of known public Nitter instances
ALL_NITTER_INSTANCES = [
    "https://nitter.net",
    "https://nitter.privacydev.net",
    "https://nitter.poast.org",
    "https://nitter.1d4.us",
    "https://nitter.fdn.fr",
    "https://nitter.kavin.rocks",
    "https://nitter.unixfox.eu",
    "https://nitter.moomoo.me",
    "https://nitter.ir",
    "https://nitter.tiekoetter.com",
    "https://nitter.rawbit.ninja",
    "https://nitter.mint.lgbt",
]

# RSS fallback sources (no scraping needed — structured XML)
RSS_SOURCES = [
    "https://techcrunch.com/tag/artificial-intelligence/feed/",
    "https://venturebeat.com/category/ai/feed/",
    "https://feeds.feedburner.com/TechCrunch",
]


# ── HEALTH CACHE ──────────────────────────────────────────────────────────────
class InstanceHealthCache:
    def __init__(self):
        self._data = {}
        self._load()

    def _load(self):
        if HEALTH_CACHE_FILE.exists():
            try:
                self._data = json.loads(HEALTH_CACHE_FILE.read_text())
            except Exception:
                self._data = {}

    def _save(self):
        HEALTH_CACHE_FILE.parent.mkdir(exist_ok=True)
        HEALTH_CACHE_FILE.write_text(json.dumps(self._data, indent=2))

    def get_healthy(self) -> list[dict]:
        """Return cached healthy instances, sorted by response time"""
        now = time.time()
        valid = [
            v for v in self._data.values()
            if v.get("healthy") and (now - v.get("checked_at", 0)) < (HEALTH_TTL_MIN * 60)
        ]
        return sorted(valid, key=lambda x: x.get("response_ms", 9999))

    def update(self, url: str, healthy: bool, response_ms: float = 0):
        self._data[url] = {
            "url":         url,
            "healthy":     healthy,
            "response_ms": response_ms,
            "checked_at":  time.time(),
        }
        self._save()

    def needs_refresh(self) -> bool:
        if not self._data:
            return True
        oldest = min(v.get("checked_at", 0) for v in self._data.values())
        return (time.time() - oldest) > (HEALTH_TTL_MIN * 60)


# ── INSTANCE HEALTH CHECKER ───────────────────────────────────────────────────
async def check_instance_health(
    session: aiohttp.ClientSession,
    url: str
) -> dict:
    """Ping a Nitter instance and measure response time"""
    start = time.time()
    try:
        async with session.get(
            f"{url}/search?q=test&f=tweets",
            headers={"User-Agent": "Mozilla/5.0 (compatible; health-check/1.0)"},
            timeout=aiohttp.ClientTimeout(total=6),
            allow_redirects=False,
        ) as resp:
            ms = round((time.time() - start) * 1000)
            # 200 or 302 = alive; 429/503 = alive but rate limited
            healthy = resp.status in (200, 302, 429, 503)
            usable  = resp.status == 200
            return {"url": url, "healthy": usable, "status": resp.status, "response_ms": ms}
    except Exception:
        return {"url": url, "healthy": False, "status": 0, "response_ms": 9999}


async def refresh_instance_health(cache: InstanceHealthCache) -> list[str]:
    """Check all instances in parallel, update cache, return healthy URLs"""
    log("NITR", f"Health-checking {len(ALL_NITTER_INSTANCES)} Nitter instances...")

    async with aiohttp.ClientSession() as session:
        results = await asyncio.gather(*[
            check_instance_health(session, url)
            for url in ALL_NITTER_INSTANCES
        ])

    healthy_urls = []
    for r in results:
        cache.update(r["url"], r["healthy"], r.get("response_ms", 9999))
        if r["healthy"]:
            healthy_urls.append(r["url"])
            log("NITR", f"  ✅ {r['url'].split('//')[1]:<35} {r['response_ms']}ms")
        else:
            log("NITR", f"  ❌ {r['url'].split('//')[1]:<35} (HTTP {r['status']})")

    log("NITR", f"  {len(healthy_urls)}/{len(ALL_NITTER_INSTANCES)} instances healthy")
    return healthy_urls


# ── NITTER TWEET PARSER ───────────────────────────────────────────────────────
class TweetParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tweets      = []
        self._current    = {}
        self._in_content = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        cls   = attrs.get("class", "")

        if "timeline-item" in cls:
            self._current = {"text": "", "link": "", "followers": 0}

        if "tweet-content" in cls:
            self._in_content = True

        if tag == "a" and "tweet-link" in cls:
            href = attrs.get("href", "")
            if href:
                self._current["link"] = f"https://x.com{href}"

    def handle_endtag(self, tag):
        if tag == "div":
            if self._in_content:
                self._in_content = False
            if self._current.get("text"):
                self.tweets.append(dict(self._current))
                self._current = {}

    def handle_data(self, data):
        data = data.strip()
        if data and self._in_content:
            self._current["text"] = self._current.get("text", "") + " " + data


# ── RSS FALLBACK PARSER ───────────────────────────────────────────────────────
async def scrape_rss_fallback(
    session: aiohttp.ClientSession,
    keyword: str
) -> list[dict]:
    """
    Fallback: scrape tech RSS feeds for startup keywords.
    Less targeted than Nitter but always works.
    """
    tweets = []
    for rss_url in RSS_SOURCES:
        try:
            async with session.get(
                rss_url,
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    content = await resp.text()
                    # Extract titles and descriptions from RSS XML
                    titles = re.findall(r'<title><!\[CDATA\[(.*?)\]\]></title>', content)
                    titles += re.findall(r'<title>(.*?)</title>', content)
                    links  = re.findall(r'<link>(https?://[^<]+)</link>', content)

                    for i, title in enumerate(titles):
                        if keyword.lower() in title.lower():
                            tweets.append({
                                "text":      title,
                                "link":      links[i] if i < len(links) else "",
                                "followers": 5000,  # assume decent reach for major tech blogs
                                "source":    "rss",
                            })
        except Exception:
            continue

    return tweets


# ── RELIABLE SCANNER (drop-in replacement for scan_nitter) ───────────────────
class ReliableNitterScanner:
    """
    Replaces the basic scan_nitter function in vc_scraper.py.
    Automatically manages instance health, rotates, falls back to RSS.
    """

    def __init__(self):
        self.cache          = InstanceHealthCache()
        self._healthy_urls  = []
        self._instance_idx  = 0

    async def ensure_healthy_instances(self, session: aiohttp.ClientSession):
        """Refresh instance health if stale"""
        if self.cache.needs_refresh() or not self._healthy_urls:
            self._healthy_urls = await refresh_instance_health(self.cache)
        else:
            # Use cached list
            cached = self.cache.get_healthy()
            self._healthy_urls = [c["url"] for c in cached]

    def _next_instance(self) -> str | None:
        """Round-robin through healthy instances"""
        if not self._healthy_urls:
            return None
        url = self._healthy_urls[self._instance_idx % len(self._healthy_urls)]
        self._instance_idx += 1
        return url

    async def scan(
        self,
        session: aiohttp.ClientSession,
        keyword: str
    ) -> list[dict]:
        """Scan for a keyword — tries Nitter instances, falls back to RSS"""
        await self.ensure_healthy_instances(session)

        # Try up to 3 different Nitter instances
        for attempt in range(min(3, len(self._healthy_urls))):
            instance = self._next_instance()
            if not instance:
                break

            try:
                url = f"{instance}/search?q={keyword.replace(' ', '+')}&f=tweets"
                headers = {
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0",
                }
                async with session.get(
                    url, headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status == 200:
                        html = await resp.text()
                        parser = TweetParser()
                        parser.feed(html)
                        for t in parser.tweets:
                            t["keyword"] = keyword
                            t["source"]  = instance

                        if parser.tweets:
                            log("NITR", f"  [{instance.split('//')[1].split('/')[0]}] "
                                        f"'{keyword}': {len(parser.tweets)} tweets")
                            return parser.tweets

                    elif resp.status == 429:
                        # Rate limited — mark as temporarily unhealthy, try next
                        self.cache.update(instance, False)
                        if instance in self._healthy_urls:
                            self._healthy_urls.remove(instance)
                        continue

            except asyncio.TimeoutError:
                # Slow instance — skip it
                if instance in self._healthy_urls:
                    self._healthy_urls.remove(instance)
                continue
            except Exception:
                continue

        # All Nitter instances failed — use RSS fallback
        log("NITR", f"  All Nitter instances failed for '{keyword}' — using RSS fallback")
        return await scrape_rss_fallback(session, keyword)
