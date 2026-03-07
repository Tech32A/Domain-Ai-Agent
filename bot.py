"""
pricing/comparable_sales.py — Real .ai domain sales data engine

Scrapes NameBio + DNJournal for actual recent .ai domain sales,
builds a local pricing model, gives every domain a data-backed
asking price instead of a guess.
"""

import re
import json
import asyncio
import aiohttp
from pathlib import Path
from datetime import datetime, timedelta
from html.parser import HTMLParser
from core.logger import log

SALES_CACHE = Path(__file__).parent.parent / "data" / "sales_cache.json"
CACHE_MAX_AGE_HOURS = 24  # refresh sales data once per day


# ── NAMEBIO PARSER ────────────────────────────────────────────────────────────
class NameBioParser(HTMLParser):
    """Parse NameBio search results for .ai domain sales"""

    def __init__(self):
        super().__init__()
        self.sales       = []
        self._in_row     = False
        self._cell_idx   = 0
        self._current    = {}
        self._in_cell    = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "tr":
            self._in_row  = True
            self._cell_idx = 0
            self._current  = {}
        if tag == "td" and self._in_row:
            self._in_cell = True

    def handle_endtag(self, tag):
        if tag == "td" and self._in_row:
            self._in_cell = False
            self._cell_idx += 1
        if tag == "tr" and self._in_row:
            if self._current.get("domain") and self._current.get("price"):
                self.sales.append(dict(self._current))
            self._in_row = False

    def handle_data(self, data):
        data = data.strip()
        if not data or not self._in_cell:
            return
        if self._cell_idx == 0 and ".ai" in data.lower():
            self._current["domain"] = data.lower().strip()
        elif self._cell_idx == 1:
            # Price cell: "$12,500" or "12500"
            try:
                price = float(data.replace("$", "").replace(",", "").strip())
                if price > 0:
                    self._current["price"] = price
            except ValueError:
                pass
        elif self._cell_idx == 2:
            self._current["date"] = data.strip()


# ── SCRAPE NAMEBIO ────────────────────────────────────────────────────────────
async def scrape_namebio(session: aiohttp.ClientSession) -> list[dict]:
    """Scrape recent .ai domain sales from NameBio"""
    sales = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml",
        "Referer": "https://namebio.com",
    }

    # NameBio search for .ai TLD sales, sorted by recent
    url = "https://namebio.com/?s=&tld=ai&daterange=&price_from=500&price_to=&order=date&r=1"

    try:
        async with session.get(url, headers=headers,
                               timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status == 200:
                html = await resp.text()
                parser = NameBioParser()
                parser.feed(html)
                sales.extend(parser.sales)
                log("PRICE", f"  NameBio: {len(parser.sales)} .ai sales found")
            else:
                log("WARN", f"  NameBio: HTTP {resp.status}")
    except Exception as e:
        log("WARN", f"  NameBio error: {str(e)[:60]}")

    return sales


# ── SCRAPE DNJOURNAL ──────────────────────────────────────────────────────────
async def scrape_dnjournal(session: aiohttp.ClientSession) -> list[dict]:
    """Scrape DNJournal weekly sales charts for .ai domains"""
    sales = []
    headers = {"User-Agent": "Mozilla/5.0 (compatible; research-bot/1.0)"}

    url = "https://www.dnjournal.com/ytd-sales-charts.htm"

    try:
        async with session.get(url, headers=headers,
                               timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status == 200:
                html = await resp.text()
                # Extract .ai domain + price pairs from page text
                # DNJournal format: "domain.ai.....$XX,XXX"
                pattern = r'([a-z0-9\-]{2,30}\.ai)\s*[\.\s]+\$?([\d,]+)'
                matches = re.findall(pattern, html, re.IGNORECASE)
                for domain, price_str in matches:
                    try:
                        price = float(price_str.replace(",", ""))
                        if price >= 500:
                            sales.append({
                                "domain": domain.lower(),
                                "price":  price,
                                "date":   "recent",
                                "source": "dnjournal"
                            })
                    except ValueError:
                        continue
                log("PRICE", f"  DNJournal: {len(sales)} .ai sales found")
            else:
                log("WARN", f"  DNJournal: HTTP {resp.status}")
    except Exception as e:
        log("WARN", f"  DNJournal error: {str(e)[:60]}")

    return sales


# ── PRICING MODEL ─────────────────────────────────────────────────────────────
class PricingEngine:
    """
    Builds a local model from scraped sales data.
    Uses comparable sales to price any domain.
    """

    def __init__(self):
        self.sales = []
        self._load_cache()

    def _load_cache(self):
        if SALES_CACHE.exists():
            try:
                data = json.loads(SALES_CACHE.read_text())
                age_hours = (datetime.now() - datetime.fromisoformat(data["updated"])).total_seconds() / 3600
                if age_hours < CACHE_MAX_AGE_HOURS:
                    self.sales = data["sales"]
                    log("PRICE", f"  Loaded {len(self.sales)} cached sales (age: {age_hours:.0f}h)")
                    return
            except Exception:
                pass
        self.sales = []

    def _save_cache(self):
        SALES_CACHE.parent.mkdir(exist_ok=True)
        SALES_CACHE.write_text(json.dumps({
            "updated": datetime.now().isoformat(),
            "sales":   self.sales,
        }, indent=2))

    async def refresh(self):
        """Re-scrape sales data from all sources"""
        log("PRICE", "Refreshing comparable sales data...")
        async with aiohttp.ClientSession() as session:
            nb, dj = await asyncio.gather(
                scrape_namebio(session),
                scrape_dnjournal(session),
                return_exceptions=True
            )
            all_sales = []
            if isinstance(nb, list): all_sales.extend(nb)
            if isinstance(dj, list): all_sales.extend(dj)

        # Deduplicate
        seen = set()
        unique = []
        for s in all_sales:
            if s["domain"] not in seen:
                seen.add(s["domain"])
                unique.append(s)

        self.sales = unique
        self._save_cache()
        log("PRICE", f"  Total comparable sales: {len(self.sales)}")

    def price_domain(self, domain: str) -> dict:
        """
        Return data-backed pricing for a domain.
        Finds comparable sales by:
        1. Exact match
        2. Same word length + similar keyword
        3. Same TLD + similar character count
        """
        name = domain.replace(".ai", "").replace(".io", "").replace(".com", "").lower()
        tld  = "." + domain.split(".")[-1]

        # 1. Exact match
        exact = [s for s in self.sales if s["domain"] == domain]
        if exact:
            price = exact[0]["price"]
            return {
                "suggested_ask":  round(price * 1.2),   # 20% above last sale
                "comp_low":       price,
                "comp_high":      round(price * 2.0),
                "confidence":     "high",
                "basis":          f"Exact match sale: {domain} = ${price:,.0f}",
                "comparables":    exact[:3],
            }

        # 2. Same character count + same TLD
        tld_comps = [
            s for s in self.sales
            if s["domain"].endswith(tld)
            and abs(len(s["domain"].replace(tld,"")) - len(name)) <= 2
        ]

        if tld_comps:
            prices   = sorted([s["price"] for s in tld_comps])
            p25      = prices[len(prices)//4]
            p75      = prices[3*len(prices)//4]
            median   = prices[len(prices)//2]
            return {
                "suggested_ask":  round(median * 1.15),
                "comp_low":       p25,
                "comp_high":      p75,
                "confidence":     "medium",
                "basis":          f"{len(tld_comps)} comparable {tld} sales (similar length)",
                "comparables":    tld_comps[:5],
            }

        # 3. All .ai sales as baseline
        ai_sales = [s for s in self.sales if s["domain"].endswith(".ai")]
        if ai_sales:
            prices = sorted([s["price"] for s in ai_sales])
            median = prices[len(prices)//2]
            return {
                "suggested_ask":  round(median * 0.8),
                "comp_low":       prices[len(prices)//4],
                "comp_high":      prices[3*len(prices)//4],
                "confidence":     "low",
                "basis":          f"Based on {len(ai_sales)} .ai sales (no close comps found)",
                "comparables":    [],
            }

        # No data yet
        return {
            "suggested_ask":  None,
            "comp_low":       None,
            "comp_high":      None,
            "confidence":     "none",
            "basis":          "No comparable sales data yet — run refresh()",
            "comparables":    [],
        }

    def enrich_results(self, results: list[dict]) -> list[dict]:
        """Add pricing data to a list of domain results"""
        for r in results:
            pricing = self.price_domain(r["domain"])
            r["suggested_ask"] = pricing["suggested_ask"]
            r["price_basis"]   = pricing["basis"]
            r["price_confidence"] = pricing["confidence"]
            r["comparables"]   = pricing.get("comparables", [])
        return results
