"""hunters/expiry_hunter.py — Monitors expiring/dropping .ai domains"""
import re
import asyncio
import aiohttp
from datetime import datetime
from core.logger import log

# Drop list sources that have .ai domain data
DROP_SOURCES = [
    {
        "name":    "ExpiredDomains.net",
        "url":     "https://www.expireddomains.net/deleted-domains/?ftlds[]=ai&start=0",
        "pattern": r'<td[^>]*>\s*<a[^>]*>([a-z0-9\-]{2,30}\.ai)</a>',
    },
    {
        "name":    "DropCatch",
        "url":     "https://www.dropcatch.com/domain/search?q=.ai&type=all",
        "pattern": r'"domain"\s*:\s*"([a-z0-9\-]{2,30}\.ai)"',
    },
]

# Fallback: scrape WHOIS expiry data for known high-value domains
WATCHLIST = [
    # High-value .ai domains to monitor for expiry
    "chat.ai", "search.ai", "hire.ai", "pay.ai", "therapy.ai",
    "coach.ai", "write.ai", "design.ai", "agent.ai", "model.ai",
    "predict.ai", "automate.ai", "analyze.ai", "optimize.ai",
    "audit.ai", "contracts.ai", "discovery.ai", "triage.ai",
    "kyc.ai", "fraud.ai", "compliance.ai", "portfolio.ai",
    "tutor.ai", "assessment.ai", "curriculum.ai", "upskill.ai",
]

WHOISXML_KEY = __import__("os").getenv("WHOISXML_API_KEY", "")


class ExpiryHunter:
    async def scan(self) -> list[dict]:
        expiring = []

        # 1. Scrape public drop lists
        drop_results = await self._scrape_drop_lists()
        expiring.extend(drop_results)
        log("HUNT", f"  Drop lists: {len(drop_results)} .ai domains found")

        # 2. Check WHOIS expiry on watchlist
        watchlist_results = await self._check_watchlist_expiry()
        expiring.extend(watchlist_results)
        log("HUNT", f"  Watchlist WHOIS: {len(watchlist_results)} expiring soon")

        # Deduplicate
        seen = set()
        unique = []
        for r in expiring:
            if r["domain"] not in seen:
                seen.add(r["domain"])
                unique.append(r)

        return unique

    async def _scrape_drop_lists(self) -> list[dict]:
        results = []
        async with aiohttp.ClientSession() as session:
            for source in DROP_SOURCES:
                try:
                    headers = {"User-Agent": "Mozilla/5.0 (compatible; domain-research-bot/1.0)"}
                    async with session.get(
                        source["url"], headers=headers,
                        timeout=aiohttp.ClientTimeout(total=15)
                    ) as resp:
                        if resp.status == 200:
                            html = await resp.text()
                            matches = re.findall(source["pattern"], html, re.IGNORECASE)
                            for domain in matches:
                                domain = domain.lower().strip()
                                if domain.endswith(".ai"):
                                    results.append({
                                        "domain":      domain,
                                        "source":      source["name"],
                                        "expiry_date": None,
                                        "status":      "dropping",
                                    })
                        elif resp.status == 403:
                            log("WARN", f"  {source['name']} blocked (403) — may need proxy")
                except Exception as e:
                    log("WARN", f"  {source['name']} error: {str(e)[:60]}")
        return results

    async def _check_watchlist_expiry(self) -> list[dict]:
        """Check WHOIS expiry dates on high-value watchlist domains"""
        if not WHOISXML_KEY:
            return []

        results = []
        today = datetime.now()

        async with aiohttp.ClientSession() as session:
            for domain in WATCHLIST:
                try:
                    url = (f"https://www.whoisxmlapi.com/whoisserver/WhoisService"
                           f"?apiKey={WHOISXML_KEY}&domainName={domain}&outputFormat=JSON")
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            expiry_str = (data.get("WhoisRecord", {})
                                             .get("registryData", {})
                                             .get("expiresDate"))
                            if expiry_str:
                                try:
                                    # Parse common WHOIS date formats
                                    for fmt in ["%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d", "%d-%b-%Y"]:
                                        try:
                                            expiry = datetime.strptime(expiry_str[:20], fmt)
                                            days_left = (expiry - today).days
                                            # Flag if expiring within 90 days
                                            if 0 < days_left <= 90:
                                                results.append({
                                                    "domain":      domain,
                                                    "source":      "watchlist_whois",
                                                    "expiry_date": expiry_str,
                                                    "days_left":   days_left,
                                                    "status":      "expiring_soon",
                                                })
                                            break
                                        except ValueError:
                                            continue
                                except Exception:
                                    pass
                    await asyncio.sleep(0.5)
                except Exception:
                    continue

        return results
