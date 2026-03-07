"""
generators/vc_scraper.py — X/Twitter startup buzz scanner via Nitter
Replaces the original VC news scraper.

Scans Nitter (free Twitter mirror) for startup buzz keywords,
extracts brand words, generates .ai/.io/.com domain variants,
checks availability via Porkbun API.

Output per domain:
  {
    "domain":        "ManusForge.ai",
    "available":     true,
    "price":         9.73,
    "source_tweet":  "https://x.com/user/status/123456"
  }
"""

import os
import re
import json
import asyncio
import aiohttp
from html.parser import HTMLParser
from core.logger import log

# ── CONFIG ────────────────────────────────────────────────────────────────────
PORKBUN_API_KEY    = os.getenv("PORKBUN_API_KEY", "")
PORKBUN_SECRET_KEY = os.getenv("PORKBUN_SECRET_KEY", "")

# Nitter public instances (fallback chain if one is down)
NITTER_INSTANCES = [
    "https://nitter.net",
    "https://nitter.privacydev.net",
    "https://nitter.poast.org",
    "https://nitter.1d4.us",
]

# Keywords to search for startup buzz
BUZZ_KEYWORDS = [
    "AI agent",
    "just raised",
    "launching soon",
    "building in public",
    "new tool",
    "just launched",
    "we raised",
    "excited to announce",
]

# Domain variant suffixes and TLDs
SUFFIXES = ["AI", "Bot", "Labs", "Forge", "HQ", "Pro", "IO", "App", "Co"]
TLDS     = [".ai", ".io", ".com"]

# Min follower count to consider a tweet worth acting on
MIN_FOLLOWERS = 1000

# Max domain name length before TLD (e.g. "ManusForge" = 10 chars)
MAX_NAME_LENGTH = 12


# ── NITTER HTML PARSER ────────────────────────────────────────────────────────
class NitterParser(HTMLParser):
    """Parses Nitter search result pages to extract tweets + metadata"""

    def __init__(self):
        super().__init__()
        self.tweets      = []
        self._current    = {}
        self._in_content = False
        self._in_stats   = False
        self._tag_stack  = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self._tag_stack.append(tag)

        if tag == "div" and "timeline-item" in attrs.get("class", ""):
            self._current = {"text": "", "link": "", "followers": 0}

        if tag == "div" and "tweet-content" in attrs.get("class", ""):
            self._in_content = True

        if tag == "a" and "tweet-link" in attrs.get("class", ""):
            href = attrs.get("href", "")
            if href:
                self._current["link"] = f"https://x.com{href}"

        if tag == "span" and "followers" in attrs.get("class", ""):
            self._in_stats = True

    def handle_endtag(self, tag):
        if self._tag_stack:
            self._tag_stack.pop()
        if tag == "div" and self._in_content:
            self._in_content = False
        if tag == "div" and self._current.get("text"):
            self.tweets.append(dict(self._current))
            self._current = {}

    def handle_data(self, data):
        data = data.strip()
        if not data:
            return
        if self._in_content:
            self._current["text"] = self._current.get("text", "") + " " + data
        if self._in_stats:
            try:
                clean = data.replace(",", "").replace("K", "000").replace("M", "000000")
                self._current["followers"] = int(float(clean))
            except ValueError:
                pass
            self._in_stats = False


# ── BRAND WORD EXTRACTOR ──────────────────────────────────────────────────────
def extract_brand_words(tweet_text: str) -> list[str]:
    """Pull candidate brand words from a tweet"""
    brands = set()

    # Quoted words
    quoted = re.findall(r'["\u201c\u201d]([A-Za-z][A-Za-z0-9]{2,10})["\u201c\u201d]', tweet_text)
    brands.update(quoted)

    # Capitalized words (not stopwords)
    stopwords = {
        "The","A","An","We","Our","I","My","This","That","It","Is","Are",
        "AI","ML","API","SaaS","MVP","YC","VC","CEO","CTO","Just","New",
        "Now","Today","When","What","How","Why","For","With","From","After",
    }
    cap_words = re.findall(r'\b([A-Z][a-z]{2,10})\b', tweet_text)
    for w in cap_words:
        if w not in stopwords:
            brands.add(w)

    # Words after trigger verbs
    triggers = r'(?:launching|building|introducing|announcing|releasing|created?|made?|built)\s+([A-Za-z][A-Za-z0-9]{2,10})'
    triggered = re.findall(triggers, tweet_text, re.IGNORECASE)
    brands.update([w.capitalize() for w in triggered])

    clean = [w for w in brands if w.isalpha() and 3 <= len(w) <= 10]
    return clean[:4]


# ── DOMAIN VARIANT GENERATOR ──────────────────────────────────────────────────
def generate_variants(brand_word: str) -> list[str]:
    """Generate short domain variants from a brand word"""
    variants = []
    brand = brand_word.capitalize()

    for suffix in SUFFIXES:
        name = f"{brand}{suffix}"
        if len(name) <= MAX_NAME_LENGTH:
            for tld in TLDS:
                variants.append(f"{name}{tld}")

    if len(brand) >= 4:
        variants.append(f"{brand}.ai")
        variants.append(f"{brand}.io")

    return variants


# ── PORKBUN AVAILABILITY CHECK ────────────────────────────────────────────────
async def check_porkbun(session: aiohttp.ClientSession, domain: str) -> dict:
    """Check domain availability + price via Porkbun API"""
    if not PORKBUN_API_KEY:
        return {"domain": domain, "available": None, "price": "unknown"}

    try:
        payload = {
            "apikey":       PORKBUN_API_KEY,
            "secretapikey": PORKBUN_SECRET_KEY,
        }
        url = f"https://porkbun.com/api/json/v3/domain/check/{domain}"
        async with session.post(
            url, json=payload,
            timeout=aiohttp.ClientTimeout(total=8)
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                if data.get("status") == "SUCCESS":
                    info = data.get("response", [{}])
                    if isinstance(info, list) and info:
                        info = info[0]
                    avail = info.get("avail", "no").lower() == "yes"
                    try:
                        price = float(info.get("price", 0))
                    except (ValueError, TypeError):
                        price = "unknown"
                    return {"domain": domain, "available": avail, "price": price}
            return {"domain": domain, "available": None, "price": "unknown"}
    except Exception as e:
        return {"domain": domain, "available": None, "price": "unknown", "error": str(e)[:40]}


# ── NITTER SCANNER ────────────────────────────────────────────────────────────
async def scan_nitter(session: aiohttp.ClientSession, keyword: str) -> list[dict]:
    """Scrape Nitter search results for a keyword"""
    tweets = []

    for instance in NITTER_INSTANCES:
        try:
            url = f"{instance}/search?q={keyword.replace(' ', '+')}&f=tweets"
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/120.0.0.0 Safari/537.36",
            }
            async with session.get(
                url, headers=headers,
                timeout=aiohttp.ClientTimeout(total=12)
            ) as resp:
                if resp.status == 200:
                    html = await resp.text()
                    parser = NitterParser()
                    parser.feed(html)
                    for t in parser.tweets:
                        t["keyword"] = keyword
                    tweets.extend(parser.tweets)
                    log("GEN", f"  Nitter [{instance.split('/')[2]}] '{keyword}': {len(parser.tweets)} tweets")
                    break
                elif resp.status in (429, 503):
                    continue
        except Exception:
            continue

    return tweets


# ── MAIN CLASS (drop-in replacement) ─────────────────────────────────────────
class VCScraper:
    """
    Drop-in replacement for original VCScraper.
    Scans X/Twitter via Nitter for startup buzz,
    generates domain variants, checks via Porkbun.
    """

    def __init__(self):
        self.rich_results = []

    async def generate(self, limit: int = 100) -> list[str]:
        all_tweets   = []
        seen_domains = set()

        async with aiohttp.ClientSession() as session:
            # 1. Scrape Nitter for all buzz keywords in parallel
            tasks   = [scan_nitter(session, kw) for kw in BUZZ_KEYWORDS]
            batches = await asyncio.gather(*tasks, return_exceptions=True)

            for batch in batches:
                if isinstance(batch, list):
                    all_tweets.extend(batch)

            log("GEN", f"  Total tweets scraped: {len(all_tweets)}")

            # 2. Filter by followers or funding signal
            filtered = [
                t for t in all_tweets
                if t.get("followers", 0) >= MIN_FOLLOWERS
                or any(kw in t.get("text", "").lower()
                       for kw in ["raised", "funding", "seed", "series"])
            ]
            log("GEN", f"  After filter: {len(filtered)} tweets")

            # 3. Extract brand words → generate domain variants
            candidate_domains = {}
            for tweet in filtered:
                brands = extract_brand_words(tweet.get("text", ""))
                for brand in brands:
                    for domain in generate_variants(brand):
                        if domain not in seen_domains:
                            seen_domains.add(domain)
                            candidate_domains[domain] = tweet.get("link", "")

            log("GEN", f"  Variants generated: {len(candidate_domains)}")

            # 4. Check availability via Porkbun
            sem = asyncio.Semaphore(5)

            async def check_with_sem(domain, tweet_url):
                async with sem:
                    await asyncio.sleep(0.3)
                    result = await check_porkbun(session, domain)
                    result["source_tweet"] = tweet_url
                    return result

            domain_list = list(candidate_domains.items())[:limit]
            checked = await asyncio.gather(*[
                check_with_sem(d, url) for d, url in domain_list
            ])

        # 5. Keep only available domains
        available = [r for r in checked if r.get("available") is True]
        self.rich_results = available
        log("GEN", f"  Available via Porkbun: {len(available)}")

        return [r["domain"] for r in available]

    def get_rich_results(self) -> str:
        """
        Returns the clean JSON array from your original system prompt format.
        Call after generate() for full output with prices + tweet links.
        """
        return json.dumps(self.rich_results, indent=2)
