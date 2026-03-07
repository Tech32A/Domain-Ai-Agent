"""
hunters/dropcatch.py — DropCatch backorder automation

Automatically places backorders on high-value expiring .ai domains
via DropCatch's API/web interface.

How it works:
1. Expiry hunter finds domains expiring in < 90 days
2. This module scores them and places backorders on score >= threshold
3. DropCatch holds a "backorder credit" ($25 default) — only charges
   if they successfully catch the domain at drop
4. Daily backorder cap prevents runaway spending

DropCatch API docs: https://www.dropcatch.com/api (requires account)
Alternative: GoDaddy Backorder API (also supported here as fallback)
"""

import os
import json
import asyncio
import aiohttp
from datetime import datetime, date
from pathlib import Path
from core.logger import log
from core.database import DomainDB

# ── CONFIG ────────────────────────────────────────────────────────────────────
DROPCATCH_USERNAME       = os.getenv("DROPCATCH_USERNAME", "")
DROPCATCH_PASSWORD       = os.getenv("DROPCATCH_PASSWORD", "")
GODADDY_KEY              = os.getenv("GODADDY_API_KEY", "")
GODADDY_SECRET           = os.getenv("GODADDY_API_SECRET", "")

BACKORDER_MIN_SCORE      = int(os.getenv("BACKORDER_MIN_SCORE", "88"))
BACKORDER_MAX_PRICE      = float(os.getenv("BACKORDER_MAX_PRICE", "25.0"))
DAILY_BACKORDER_CAP      = float(os.getenv("DAILY_BACKORDER_CAP", "75.0"))
ENABLE_BACKORDER         = os.getenv("ENABLE_BACKORDER", "false").lower() == "true"
BACKORDER_DRY_RUN        = os.getenv("BACKORDER_DRY_RUN", "true").lower() == "true"

BACKORDER_LOG = Path(__file__).parent.parent / "data" / "backorders.json"


# ── BACKORDER TRACKER ─────────────────────────────────────────────────────────
class BackorderTracker:
    def __init__(self):
        BACKORDER_LOG.parent.mkdir(exist_ok=True)
        self._load()

    def _load(self):
        today = str(date.today())
        if BACKORDER_LOG.exists():
            data = json.loads(BACKORDER_LOG.read_text())
            if data.get("date") == today:
                self.data = data
                return
        self.data = {"date": today, "spent": 0.0, "backorders": []}

    def _save(self):
        BACKORDER_LOG.write_text(json.dumps(self.data, indent=2))

    @property
    def spent_today(self) -> float:
        return self.data["spent"]

    def can_spend(self, amount: float) -> bool:
        return (self.data["spent"] + amount) <= DAILY_BACKORDER_CAP

    def record(self, domain: str, price: float, service: str, expiry: str):
        self.data["spent"] += price
        self.data["backorders"].append({
            "domain":    domain,
            "price":     price,
            "service":   service,
            "expiry":    expiry,
            "placed_at": datetime.now().isoformat(),
        })
        self._save()


# ── DROPCATCH BACKORDER ───────────────────────────────────────────────────────
async def place_dropcatch_backorder(
    session: aiohttp.ClientSession,
    domain: str,
) -> dict:
    """
    Place a backorder on DropCatch.
    DropCatch charges ~$25 only if they WIN the domain at drop auction.
    """
    if not DROPCATCH_USERNAME:
        return {"success": False, "message": "DropCatch credentials not configured"}

    try:
        # Step 1: Login to get session cookie
        login_payload = {
            "username": DROPCATCH_USERNAME,
            "password": DROPCATCH_PASSWORD,
        }
        async with session.post(
            "https://www.dropcatch.com/account/login",
            data=login_payload,
            timeout=aiohttp.ClientTimeout(total=15),
            allow_redirects=True,
        ) as resp:
            if resp.status not in (200, 302):
                return {"success": False, "message": f"Login failed: HTTP {resp.status}"}

        # Step 2: Place backorder
        async with session.post(
            "https://www.dropcatch.com/domain/backorder",
            data={"domain": domain},
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            text = await resp.text()
            if resp.status == 200 and ("success" in text.lower() or "backorder" in text.lower()):
                return {"success": True, "service": "dropcatch", "message": "Backorder placed"}
            return {"success": False, "message": f"Unexpected response: {text[:100]}"}

    except Exception as e:
        return {"success": False, "message": str(e)[:80]}


# ── GODADDY BACKORDER (fallback) ──────────────────────────────────────────────
async def place_godaddy_backorder(
    session: aiohttp.ClientSession,
    domain: str,
) -> dict:
    """
    Place a domain backorder via GoDaddy API.
    GoDaddy charges ~$5-20 depending on TLD.
    """
    if not GODADDY_KEY:
        return {"success": False, "message": "GoDaddy API key not configured"}

    try:
        headers = {
            "Authorization": f"sso-key {GODADDY_KEY}:{GODADDY_SECRET}",
            "Content-Type": "application/json",
        }
        payload = {"domain": domain}
        async with session.post(
            "https://api.godaddy.com/v1/domains/backorders",
            json=payload, headers=headers,
            timeout=aiohttp.ClientTimeout(total=12),
        ) as resp:
            if resp.status in (200, 201):
                return {"success": True, "service": "godaddy", "message": "Backorder placed"}
            data = await resp.json()
            return {"success": False, "message": data.get("message", f"HTTP {resp.status}")}
    except Exception as e:
        return {"success": False, "message": str(e)[:80]}


# ── MAIN DROPCATCH MODULE ─────────────────────────────────────────────────────
class DropCatchAutomator:
    def __init__(self):
        self.db      = DomainDB()
        self.tracker = BackorderTracker()
        self.placed_this_run = []

    async def process(self, expiring_results: list[dict]) -> list[dict]:
        """
        Takes expiring domain results from expiry_hunter,
        places backorders on high-score ones within budget.
        """
        if not ENABLE_BACKORDER:
            log("DROP", "Backorder disabled (set ENABLE_BACKORDER=true to enable)")
            return []

        if BACKORDER_DRY_RUN:
            log("DROP", "🔍 DRY RUN — no actual backorders will be placed")

        candidates = [
            r for r in expiring_results
            if r.get("score", 0) >= BACKORDER_MIN_SCORE
            and r.get("type") == "expiring"
            and self.tracker.can_spend(BACKORDER_MAX_PRICE)
        ]

        if not candidates:
            log("DROP", f"No expiring domains met backorder criteria (score≥{BACKORDER_MIN_SCORE})")
            return []

        log("DROP", f"{len(candidates)} expiring domains qualify for backorder")
        placed = []

        async with aiohttp.ClientSession() as session:
            for r in candidates:
                domain = r["domain"]
                expiry = r.get("expiry_date", "unknown")

                if not self.tracker.can_spend(BACKORDER_MAX_PRICE):
                    log("DROP", f"⚠ Daily backorder cap reached (${DAILY_BACKORDER_CAP})")
                    break

                log("DROP", f"{'[DRY RUN]' if BACKORDER_DRY_RUN else ''} "
                            f"Placing backorder: {domain} (score={r['score']}, expires {expiry})")

                if BACKORDER_DRY_RUN:
                    result = {"success": True, "service": "dry_run", "message": "dry_run"}
                else:
                    # Try DropCatch first, fall back to GoDaddy
                    result = await place_dropcatch_backorder(session, domain)
                    if not result["success"]:
                        log("DROP", f"  DropCatch failed — trying GoDaddy backorder...")
                        result = await place_godaddy_backorder(session, domain)

                if result["success"]:
                    self.tracker.record(
                        domain  = domain,
                        price   = BACKORDER_MAX_PRICE,
                        service = result.get("service",""),
                        expiry  = expiry,
                    )
                    placed.append({**r, "backorder": result})
                    self.placed_this_run.append(domain)
                    log("DROP", f"  ✅ Backorder placed: {domain} via {result.get('service','')}")
                else:
                    log("DROP", f"  ❌ Failed: {domain} — {result['message']}")

                await asyncio.sleep(1)

        log("DROP", f"Run complete — {len(placed)} backorders | "
                    f"${self.tracker.spent_today:.2f} / ${DAILY_BACKORDER_CAP:.2f} today")
        return placed

    def get_active_backorders(self) -> list[dict]:
        """Return all backorders placed today"""
        return self.tracker.data.get("backorders", [])
