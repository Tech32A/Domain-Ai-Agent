"""
backorder/dropcatch.py — Automated backorder placement for expiring .ai domains

When the expiry hunter finds a high-value domain expiring soon,
this module automatically places a backorder via DropCatch so you're
first in line when it drops — before the general public can register it.

DropCatch backorder = you pay ~$25, they use their proprietary
catching technology to grab the domain the millisecond it expires.
If caught, you win it. If not, you pay nothing.

Also monitors GoDaddy Auctions and NameJet for domains already in
the drop/auction pipeline.
"""

import os
import json
import asyncio
import aiohttp
from pathlib import Path
from datetime import datetime
from core.logger import log
from core.database import DomainDB

DROPCATCH_USER     = os.getenv("DROPCATCH_USERNAME", "")
DROPCATCH_PASS     = os.getenv("DROPCATCH_PASSWORD", "")
NAMECHEAP_API_KEY  = os.getenv("NAMECHEAP_API_KEY", "")
NAMECHEAP_USER     = os.getenv("NAMECHEAP_USERNAME", "")
NAMECHEAP_CLIENT_IP= os.getenv("NAMECHEAP_CLIENT_IP", "")

# Only backorder if score meets threshold
BACKORDER_MIN_SCORE  = int(os.getenv("BACKORDER_MIN_SCORE", "82"))
DROPCATCH_PRICE      = 24.98   # DropCatch standard backorder price
MAX_BACKORDERS_PER_RUN = int(os.getenv("MAX_BACKORDERS_PER_RUN", "3"))

BACKORDER_LOG = Path(__file__).parent.parent / "data" / "backorders.json"


# ── BACKORDER TRACKER ─────────────────────────────────────────────────────────
class BackorderTracker:
    def __init__(self):
        BACKORDER_LOG.parent.mkdir(exist_ok=True)
        self._load()

    def _load(self):
        if BACKORDER_LOG.exists():
            try:
                self._data = json.loads(BACKORDER_LOG.read_text())
            except Exception:
                self._data = {"backorders": []}
        else:
            self._data = {"backorders": []}

    def _save(self):
        BACKORDER_LOG.write_text(json.dumps(self._data, indent=2))

    def already_ordered(self, domain: str) -> bool:
        return any(b["domain"] == domain for b in self._data["backorders"])

    def record(self, domain: str, service: str, price: float, result: dict):
        self._data["backorders"].append({
            "domain":    domain,
            "service":   service,
            "price":     price,
            "placed_at": datetime.now().isoformat(),
            "result":    result,
        })
        self._save()

    def count_today(self) -> int:
        today = datetime.now().date().isoformat()
        return sum(
            1 for b in self._data["backorders"]
            if b.get("placed_at", "")[:10] == today
        )

    def get_all(self) -> list[dict]:
        return self._data["backorders"]


# ── DROPCATCH BACKORDER ───────────────────────────────────────────────────────
async def place_dropcatch_backorder(
    session: aiohttp.ClientSession,
    domain: str
) -> dict:
    """
    Place a backorder on DropCatch.com via their web API.
    DropCatch doesn't have a public API — this uses their
    authenticated session endpoint.
    """
    if not DROPCATCH_USER or not DROPCATCH_PASS:
        return {
            "success": False,
            "message": "DropCatch credentials not configured in .env",
            "service": "dropcatch"
        }

    try:
        # Step 1: Login to get session cookie
        login_resp = await session.post(
            "https://www.dropcatch.com/Account/Login",
            data={"UserName": DROPCATCH_USER, "Password": DROPCATCH_PASS},
            headers={"User-Agent": "Mozilla/5.0", "Content-Type": "application/x-www-form-urlencoded"},
            allow_redirects=True,
            timeout=aiohttp.ClientTimeout(total=15)
        )

        if login_resp.status not in (200, 302):
            return {"success": False, "message": f"Login failed: HTTP {login_resp.status}", "service": "dropcatch"}

        # Step 2: Place backorder
        order_resp = await session.post(
            "https://www.dropcatch.com/domain/backorder",
            json={"domain": domain},
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=aiohttp.ClientTimeout(total=15)
        )

        if order_resp.status == 200:
            data = await order_resp.json()
            success = data.get("success", False) or data.get("status") == "ok"
            return {
                "success": success,
                "message": data.get("message", "Backorder placed"),
                "service": "dropcatch",
                "order_id": data.get("orderId", ""),
            }

        return {"success": False, "message": f"HTTP {order_resp.status}", "service": "dropcatch"}

    except Exception as e:
        return {"success": False, "message": str(e)[:80], "service": "dropcatch"}


# ── NAMECHEAP BACKORDER (fallback) ────────────────────────────────────────────
async def place_namecheap_backorder(
    session: aiohttp.ClientSession,
    domain: str
) -> dict:
    """Place backorder via Namecheap API (cheaper alternative ~$10)"""
    if not NAMECHEAP_API_KEY:
        return {"success": False, "message": "Namecheap API key not configured", "service": "namecheap"}

    try:
        params = {
            "ApiUser":    NAMECHEAP_USER,
            "ApiKey":     NAMECHEAP_API_KEY,
            "UserName":   NAMECHEAP_USER,
            "Command":    "namecheap.domains.backorder.add",
            "ClientIp":   NAMECHEAP_CLIENT_IP,
            "DomainName": domain,
        }
        resp = await session.get(
            "https://api.namecheap.com/xml.response",
            params=params,
            timeout=aiohttp.ClientTimeout(total=10)
        )
        if resp.status == 200:
            text = await resp.text()
            success = 'Status="OK"' in text
            return {
                "success": success,
                "message": "Backorder placed via Namecheap" if success else "Namecheap backorder failed",
                "service": "namecheap",
            }
        return {"success": False, "message": f"HTTP {resp.status}", "service": "namecheap"}
    except Exception as e:
        return {"success": False, "message": str(e)[:80], "service": "namecheap"}


# ── CHECK GODADDY AUCTIONS ────────────────────────────────────────────────────
async def check_godaddy_auctions(
    session: aiohttp.ClientSession,
    domain: str
) -> dict | None:
    """
    Check if a domain is already in GoDaddy's expiry auction pipeline.
    If so, return auction details so you can bid directly.
    """
    godaddy_key    = os.getenv("GODADDY_API_KEY", "")
    godaddy_secret = os.getenv("GODADDY_API_SECRET", "")

    if not godaddy_key:
        return None

    try:
        url = f"https://api.godaddy.com/v1/auctions?domain={domain}&status=OPEN"
        headers = {
            "Authorization": f"sso-key {godaddy_key}:{godaddy_secret}",
            "Accept": "application/json"
        }
        resp = await session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=8))
        if resp.status == 200:
            data = await resp.json()
            auctions = data.get("auctions", [])
            if auctions:
                a = auctions[0]
                return {
                    "in_auction":   True,
                    "auction_id":   a.get("auctionId"),
                    "current_bid":  a.get("currentBid", {}).get("value"),
                    "end_time":     a.get("endTime"),
                    "bid_url":      f"https://auctions.godaddy.com/trpItemListing.aspx?miid={a.get('auctionId')}",
                }
        return None
    except Exception:
        return None


# ── MAIN BACKORDER MANAGER ────────────────────────────────────────────────────
class BackorderManager:
    def __init__(self):
        self.db      = DomainDB()
        self.tracker = BackorderTracker()

    async def process(self, expiring_results: list[dict]) -> list[dict]:
        """
        Process expiring domains — place backorders on high-score ones.
        Returns list of domains where backorders were placed.
        """
        placed = []

        # Filter to high-score expiring domains not already ordered
        candidates = [
            r for r in expiring_results
            if r.get("score", 0) >= BACKORDER_MIN_SCORE
            and r.get("type") == "expiring"
            and not self.tracker.already_ordered(r["domain"])
        ]

        if not candidates:
            log("BKORD", "No expiring candidates meet backorder threshold")
            return []

        today_count = self.tracker.count_today()
        remaining   = MAX_BACKORDERS_PER_RUN - today_count

        if remaining <= 0:
            log("BKORD", f"Daily backorder limit reached ({MAX_BACKORDERS_PER_RUN})")
            return []

        log("BKORD", f"{len(candidates)} candidates, placing up to {remaining} backorders...")

        async with aiohttp.ClientSession() as session:
            for r in candidates[:remaining]:
                domain = r["domain"]
                score  = r["score"]

                # Check GoDaddy auctions first (might already be auctioned)
                auction = await check_godaddy_auctions(session, domain)
                if auction and auction.get("in_auction"):
                    log("BKORD", f"  🔨 {domain} already in GoDaddy auction — bid at: {auction['bid_url']}")
                    r["auction"] = auction
                    placed.append(r)
                    continue

                log("BKORD", f"  Placing backorder: {domain} (score={score})...")

                # Try DropCatch first, fall back to Namecheap
                result = await place_dropcatch_backorder(session, domain)

                if not result["success"] and NAMECHEAP_API_KEY:
                    log("BKORD", f"  DropCatch failed, trying Namecheap...")
                    result = await place_namecheap_backorder(session, domain)

                self.tracker.record(domain, result.get("service", "unknown"), DROPCATCH_PRICE, result)

                if result["success"]:
                    log("BKORD", f"  ✅ Backorder placed: {domain} via {result['service']}")
                    r["backorder"] = result
                    placed.append(r)
                else:
                    log("BKORD", f"  ❌ Backorder failed: {domain} — {result['message']}")

                await asyncio.sleep(1)

        log("BKORD", f"Complete — {len(placed)} backorders placed today total: {self.tracker.count_today()}")
        return placed

    def get_pending_backorders(self) -> list[dict]:
        """Return all backorders waiting to be caught"""
        return [b for b in self.tracker.get_all() if b.get("result", {}).get("success")]
