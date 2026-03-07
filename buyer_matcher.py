"""hunters/market_hunter.py — Scans aftermarket for underpriced .ai listings"""
import re
import asyncio
import aiohttp
from core.logger import log
from core.scorer import DomainScorer

scorer = DomainScorer()

# Aftermarket sources
MARKET_SOURCES = [
    {
        "name":    "Sedo",
        "url":     "https://sedo.com/search/searchresult.php?keyword=&tld=ai&language=&minprice=&maxprice=50000&currency=USD&category=&order=price&ordertype=asc",
        "domain_pattern": r'([a-z0-9\-]{2,30}\.ai)',
        "price_pattern":  r'\$?([\d,]+)',
    },
    {
        "name":    "Afternic",
        "url":     "https://www.afternic.com/forsale?query=.ai&price_max=50000",
        "domain_pattern": r'"domain"\s*:\s*"([a-z0-9\-]{2,30}\.ai)"',
        "price_pattern":  r'"price"\s*:\s*([\d.]+)',
    },
    {
        "name":    "Dan.com",
        "url":     "https://dan.com/buy-domain/?tld=.ai&price_max=50000&sort=price_asc",
        "domain_pattern": r'([a-z0-9\-]{2,30}\.ai)',
        "price_pattern":  r'\$?([\d,]+)',
    },
]

# Max price to consider "underpriced" relative to flip score
PRICE_THRESHOLDS = {
    90: 5000,   # Score 90+ → worth buying up to $5K
    80: 2000,   # Score 80+ → worth buying up to $2K
    70: 500,    # Score 70+ → worth buying up to $500
}


class MarketHunter:
    async def scan(self) -> list[dict]:
        listings = []

        async with aiohttp.ClientSession() as session:
            for source in MARKET_SOURCES:
                try:
                    headers = {
                        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    }
                    async with session.get(
                        source["url"], headers=headers,
                        timeout=aiohttp.ClientTimeout(total=15)
                    ) as resp:
                        if resp.status == 200:
                            content = await resp.text()
                            found = self._parse_listings(content, source)
                            listings.extend(found)
                            log("HUNT", f"  {source['name']}: {len(found)} listings parsed")
                        else:
                            log("WARN", f"  {source['name']}: HTTP {resp.status}")
                except Exception as e:
                    log("WARN", f"  {source['name']} error: {str(e)[:60]}")

                await asyncio.sleep(1)

        # Filter to underpriced only
        underpriced = self._filter_underpriced(listings)
        return underpriced

    def _parse_listings(self, html: str, source: dict) -> list[dict]:
        listings = []
        domains  = re.findall(source["domain_pattern"], html, re.IGNORECASE)
        prices   = re.findall(source["price_pattern"], html, re.IGNORECASE)

        for i, domain in enumerate(domains[:50]):
            domain = domain.lower().strip()
            if not domain.endswith(".ai"):
                continue
            # Try to pair with a price
            price = None
            if i < len(prices):
                try:
                    price = float(prices[i].replace(",", ""))
                except ValueError:
                    pass

            listings.append({
                "domain":       domain,
                "market_price": price,
                "source":       source["name"],
                "status":       "for_sale",
            })

        return listings

    def _filter_underpriced(self, listings: list[dict]) -> list[dict]:
        """Keep only listings where asking price is below flip potential"""
        underpriced = []
        for listing in listings:
            score, _ = scorer.score(listing["domain"], "aftermarket")
            est_low, est_high = scorer.estimate_value(score, listing["domain"])
            market_price = listing.get("market_price")

            if market_price is None:
                # No price = might be negotiable, include at lower priority
                listing["score"] = score
                listing["est_low"] = est_low
                listing["est_high"] = est_high
                listing["margin"] = None
                underpriced.append(listing)
                continue

            # Check if price is below our estimated floor value
            max_buy = 0
            for min_score, max_price in PRICE_THRESHOLDS.items():
                if score >= min_score:
                    max_buy = max_price
                    break

            if market_price <= max_buy and market_price < est_low * 0.5:
                listing["score"]    = score
                listing["est_low"]  = est_low
                listing["est_high"] = est_high
                listing["margin"]   = round(((est_low / market_price) - 1) * 100)
                underpriced.append(listing)

        underpriced.sort(key=lambda x: -(x.get("margin") or 0))
        return underpriced
