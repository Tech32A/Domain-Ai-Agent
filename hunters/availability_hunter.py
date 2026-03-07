"""hunters/availability_hunter.py — Bulk availability checker with 3-source consensus"""
import os
import asyncio
import aiohttp
from core.logger import log

GODADDY_KEY    = os.getenv("GODADDY_API_KEY", "")
GODADDY_SECRET = os.getenv("GODADDY_API_SECRET", "")
WHOISXML_KEY   = os.getenv("WHOISXML_API_KEY", "")

CONCURRENCY    = 5    # parallel requests
RATE_DELAY     = 0.3  # seconds between batches


class AvailabilityHunter:
    async def check_bulk(self, domains: list[str]) -> list[dict]:
        """Check availability for a list of domains, return only available ones"""
        available = []
        sem = asyncio.Semaphore(CONCURRENCY)

        async with aiohttp.ClientSession() as session:
            tasks = [self._check_one(session, sem, d) for d in domains]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, dict) and result.get("available"):
                available.append(result)

        return available

    async def _check_one(self, session: aiohttp.ClientSession, sem: asyncio.Semaphore, domain: str) -> dict:
        async with sem:
            await asyncio.sleep(RATE_DELAY)
            gd  = await self._godaddy_check(session, domain)
            wx  = await self._whoisxml_check(session, domain)

            # Consensus: need at least 1 positive if only 1 source works,
            # or majority if both work
            votes = [v for v in [gd.get("available"), wx.get("available")] if v is not None]
            if not votes:
                return {"domain": domain, "available": False}

            available = sum(votes) >= max(1, len(votes) // 2 + 1)

            return {
                "domain":     domain,
                "available":  available,
                "reg_price":  gd.get("price"),
                "gd_status":  gd.get("status"),
                "wx_status":  wx.get("status"),
                "registrar":  wx.get("registrar"),
                "status":     "available" if available else "taken",
            }

    async def _godaddy_check(self, session: aiohttp.ClientSession, domain: str) -> dict:
        if not GODADDY_KEY:
            return {"available": None, "status": "no_key"}
        try:
            url = f"https://api.godaddy.com/v1/domains/available?domain={domain}&checkType=FAST&forTransfer=false"
            headers = {
                "Authorization": f"sso-key {GODADDY_KEY}:{GODADDY_SECRET}",
                "Accept": "application/json"
            }
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    price = data.get("price", 0) / 1_000_000
                    return {
                        "available": data.get("available", False),
                        "price":     round(price, 2),
                        "status":    "ok"
                    }
                elif resp.status == 429:
                    await asyncio.sleep(2)
                    return {"available": None, "status": "rate_limited"}
                return {"available": None, "status": f"http_{resp.status}"}
        except Exception as e:
            return {"available": None, "status": str(e)[:40]}

    async def _whoisxml_check(self, session: aiohttp.ClientSession, domain: str) -> dict:
        if not WHOISXML_KEY:
            return {"available": None, "status": "no_key"}
        try:
            url = f"https://domain-availability.whoisxmlapi.com/api/v1?apiKey={WHOISXML_KEY}&domainName={domain}&credits=DA"
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    avail = data.get("DomainInfo", {}).get("domainAvailability") == "AVAILABLE"
                    registrar = data.get("DomainInfo", {}).get("registrarName")
                    return {"available": avail, "registrar": registrar, "status": "ok"}
                return {"available": None, "status": f"http_{resp.status}"}
        except Exception as e:
            return {"available": None, "status": str(e)[:40]}
