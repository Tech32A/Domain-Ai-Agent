"""
generators/nitter_health.py — Nitter instance health checker + smart rotation

Fixes the reliability problem by:
1. Testing all known instances at startup
2. Ranking by response time + success rate
3. Rotating through healthy instances automatically
4. Falling back to direct RSS feeds when all Nitter instances fail
5. Caching healthy instance list so we don't re-test every scan
"""

import asyncio
import aiohttp
import json
import time
from pathlib import Path
from core.logger import log

HEALTH_CACHE = Path(__file__).parent.parent / "data" / "nitter_health.json"
CACHE_TTL    = 3600  # re-test instances every hour

# All known public Nitter instances
ALL_INSTANCES = [
    "https://nitter.net",
    "https://nitter.privacydev.net",
    "https://nitter.poast.org",
    "https://nitter.1d4.us",
    "https://nitter.esmailelbob.xyz",
    "https://nitter.tiekoetter.com",
    "https://nitter.rawbit.ninja",
    "https://nitter.moomoo.me",
    "https://nitter.cz",
    "https://nitter.unixfox.eu",
]

# RSS feed fallbacks — work even when Nitter HTML scraping fails
RSS_SEARCH_FEEDS = [
    "https://nitter.net/search/rss?q={query}",
    "https://nitter.privacydev.net/search/rss?q={query}",
]


class NitterHealthChecker:
    def __init__(self):
        self.healthy   = []
        self.last_test = 0
        self._load_cache()

    def _load_cache(self):
        if HEALTH_CACHE.exists():
            try:
                data = json.loads(HEALTH_CACHE.read_text())
                age  = time.time() - data.get("tested_at", 0)
                if age < CACHE_TTL and data.get("healthy"):
                    self.healthy   = data["healthy"]
                    self.last_test = data["tested_at"]
                    log("NITTER", f"  Loaded {len(self.healthy)} healthy instances from cache")
                    return
            except Exception:
                pass
        self.healthy = []

    def _save_cache(self):
        HEALTH_CACHE.parent.mkdir(exist_ok=True)
        HEALTH_CACHE.write_text(json.dumps({
            "tested_at": time.time(),
            "healthy":   self.healthy,
        }, indent=2))

    async def test_instance(self, session: aiohttp.ClientSession, url: str) -> dict:
        """Test a single Nitter instance — returns {url, ok, latency_ms}"""
        start = time.time()
        try:
            test_url = f"{url}/search?q=AI+startup&f=tweets"
            async with session.get(
                test_url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; health-check/1.0)"},
                timeout=aiohttp.ClientTimeout(total=8),
                allow_redirects=True,
            ) as resp:
                latency = round((time.time() - start) * 1000)
                ok = resp.status == 200 and "timeline" in (await resp.text())[:2000]
                return {"url": url, "ok": ok, "latency_ms": latency}
        except Exception:
            return {"url": url, "ok": False, "latency_ms": 9999}

    async def refresh(self, force: bool = False):
        """Test all instances, rank by latency, update healthy list"""
        age = time.time() - self.last_test
        if not force and self.healthy and age < CACHE_TTL:
            return  # still fresh

        log("NITTER", f"Testing {len(ALL_INSTANCES)} Nitter instances...")
        async with aiohttp.ClientSession() as session:
            results = await asyncio.gather(*[
                self.test_instance(session, url) for url in ALL_INSTANCES
            ])

        working = [r for r in results if r["ok"]]
        working.sort(key=lambda x: x["latency_ms"])

        self.healthy   = [r["url"] for r in working]
        self.last_test = time.time()
        self._save_cache()

        log("NITTER", f"  {len(working)}/{len(ALL_INSTANCES)} instances healthy")
        for r in working[:5]:
            log("NITTER", f"    ✓ {r['url']} ({r['latency_ms']}ms)")

    def get_instances(self) -> list[str]:
        """Return ranked healthy instances, fallback to all if none tested"""
        return self.healthy if self.healthy else ALL_INSTANCES[:3]

    async def fetch_with_fallback(
        self,
        session: aiohttp.ClientSession,
        keyword: str,
        max_retries: int = 3
    ) -> str:
        """
        Fetch Nitter search results with automatic instance rotation.
        Falls back to RSS feed if HTML scraping fails everywhere.
        """
        instances = self.get_instances()
        encoded   = keyword.replace(" ", "+")

        # Try HTML scraping first (richer data)
        for instance in instances[:max_retries]:
            try:
                url = f"{instance}/search?q={encoded}&f=tweets"
                async with session.get(
                    url,
                    headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 200:
                        content = await resp.text()
                        if "timeline-item" in content:
                            return content
                    elif resp.status == 429:
                        log("NITTER", f"  {instance} rate limited — trying next")
                        continue
            except asyncio.TimeoutError:
                log("NITTER", f"  {instance} timeout — trying next")
                continue
            except Exception:
                continue

        # Fallback: try RSS feeds (simpler format but more reliable)
        for rss_template in RSS_SEARCH_FEEDS:
            try:
                url = rss_template.format(query=encoded)
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                    if resp.status == 200:
                        content = await resp.text()
                        if "<item>" in content:
                            log("NITTER", f"  RSS fallback succeeded for '{keyword}'")
                            return content  # caller must handle RSS format too
            except Exception:
                continue

        log("NITTER", f"  All sources failed for '{keyword}'")
        return ""


# Global singleton
_checker = None

def get_health_checker() -> NitterHealthChecker:
    global _checker
    if _checker is None:
        _checker = NitterHealthChecker()
    return _checker
