"""
autoregister/auto_register.py — Auto-registers high-score domains via Porkbun API

Rules:
- Only registers if score >= AUTO_REGISTER_MIN_SCORE (default 90)
- Only registers if price <= AUTO_REGISTER_MAX_PRICE (default $15)
- Enforces daily spend cap (default $50/day)
- Logs every registration to DB + sends Telegram alert
- Dry-run mode available (set AUTO_REGISTER_DRY_RUN=true in .env)
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
PORKBUN_API_KEY        = os.getenv("PORKBUN_API_KEY", "")
PORKBUN_SECRET_KEY     = os.getenv("PORKBUN_SECRET_KEY", "")
AUTO_REGISTER_MIN_SCORE = int(os.getenv("AUTO_REGISTER_MIN_SCORE", "90"))
AUTO_REGISTER_MAX_PRICE = float(os.getenv("AUTO_REGISTER_MAX_PRICE", "15.0"))
DAILY_SPEND_CAP         = float(os.getenv("DAILY_SPEND_CAP", "50.0"))
DRY_RUN                 = os.getenv("AUTO_REGISTER_DRY_RUN", "false").lower() == "true"

# Registration contact info (required by Porkbun for domain registration)
REG_FIRST_NAME  = os.getenv("REG_FIRST_NAME", "")
REG_LAST_NAME   = os.getenv("REG_LAST_NAME", "")
REG_EMAIL       = os.getenv("REG_EMAIL", "")
REG_PHONE       = os.getenv("REG_PHONE", "")       # format: +1.2125551234
REG_ADDRESS     = os.getenv("REG_ADDRESS", "")
REG_CITY        = os.getenv("REG_CITY", "")
REG_STATE       = os.getenv("REG_STATE", "")
REG_ZIP         = os.getenv("REG_ZIP", "")
REG_COUNTRY     = os.getenv("REG_COUNTRY", "US")

# Spend tracking file
SPEND_FILE = Path(__file__).parent.parent / "data" / "daily_spend.json"


# ── SPEND TRACKER ─────────────────────────────────────────────────────────────
class SpendTracker:
    def __init__(self):
        SPEND_FILE.parent.mkdir(exist_ok=True)
        self._load()

    def _load(self):
        today = str(date.today())
        if SPEND_FILE.exists():
            data = json.loads(SPEND_FILE.read_text())
            # Reset if it's a new day
            if data.get("date") != today:
                self.data = {"date": today, "spent": 0.0, "registrations": []}
            else:
                self.data = data
        else:
            self.data = {"date": today, "spent": 0.0, "registrations": []}

    def _save(self):
        SPEND_FILE.write_text(json.dumps(self.data, indent=2))

    @property
    def spent_today(self) -> float:
        return self.data["spent"]

    @property
    def remaining(self) -> float:
        return max(0.0, DAILY_SPEND_CAP - self.data["spent"])

    def can_spend(self, amount: float) -> bool:
        return (self.data["spent"] + amount) <= DAILY_SPEND_CAP

    def record(self, domain: str, price: float):
        self.data["spent"] += price
        self.data["registrations"].append({
            "domain":    domain,
            "price":     price,
            "timestamp": datetime.now().isoformat(),
        })
        self._save()

    def summary(self) -> str:
        regs = self.data["registrations"]
        return (f"Today: ${self.data['spent']:.2f} spent / "
                f"${DAILY_SPEND_CAP:.2f} cap | "
                f"{len(regs)} domains registered")


# ── PORKBUN REGISTRATION ──────────────────────────────────────────────────────
async def register_via_porkbun(session: aiohttp.ClientSession, domain: str, years: int = 1) -> dict:
    """
    Register a domain via Porkbun API.
    Returns {"success": bool, "message": str, "price": float}
    """
    if not PORKBUN_API_KEY:
        return {"success": False, "message": "No Porkbun API key configured"}

    if not REG_EMAIL:
        return {"success": False, "message": "Registration contact info not configured in .env"}

    payload = {
        "apikey":       PORKBUN_API_KEY,
        "secretapikey": PORKBUN_SECRET_KEY,
        "years":        str(years),
        "autorenew":    "0",  # don't auto-renew — you decide after the flip
        "whoisPrivacy": "1",  # enable WHOIS privacy (free on Porkbun)
        "firstName":    REG_FIRST_NAME,
        "lastName":     REG_LAST_NAME,
        "email":        REG_EMAIL,
        "phone":        REG_PHONE,
        "address1":     REG_ADDRESS,
        "city":         REG_CITY,
        "state":        REG_STATE,
        "zip":          REG_ZIP,
        "country":      REG_COUNTRY,
    }

    try:
        url = f"https://porkbun.com/api/json/v3/domain/create/{domain}"
        async with session.post(
            url, json=payload,
            timeout=aiohttp.ClientTimeout(total=20)
        ) as resp:
            data = await resp.json()
            if data.get("status") == "SUCCESS":
                return {
                    "success": True,
                    "message": "Registered successfully",
                    "transaction_id": data.get("id", ""),
                }
            else:
                return {
                    "success": False,
                    "message": data.get("message", "Unknown error"),
                }
    except Exception as e:
        return {"success": False, "message": str(e)[:80]}


# ── MAIN AUTO-REGISTRAR ───────────────────────────────────────────────────────
class AutoRegistrar:
    def __init__(self):
        self.db      = DomainDB()
        self.tracker = SpendTracker()
        self.registered_this_run = []

    async def process(self, scored_results: list[dict]) -> list[dict]:
        """
        Takes the scored results from bot.py and auto-registers
        anything that meets the criteria.
        Returns list of successfully registered domains.
        """
        if DRY_RUN:
            log("AUTO", "🔍 DRY RUN MODE — no actual registrations will be made")

        candidates = [
            r for r in scored_results
            if r.get("score", 0) >= AUTO_REGISTER_MIN_SCORE
            and r.get("type") in ("unregistered", "expiring")
            and isinstance(r.get("reg_price"), (int, float))
            and r["reg_price"] <= AUTO_REGISTER_MAX_PRICE
            and self.tracker.can_spend(r["reg_price"])
        ]

        if not candidates:
            log("AUTO", f"No candidates met criteria (score≥{AUTO_REGISTER_MIN_SCORE}, price≤${AUTO_REGISTER_MAX_PRICE})")
            log("AUTO", self.tracker.summary())
            return []

        log("AUTO", f"{len(candidates)} candidates qualify for auto-registration")
        log("AUTO", self.tracker.summary())

        registered = []

        async with aiohttp.ClientSession() as session:
            for r in candidates:
                domain = r["domain"]
                price  = r["reg_price"]

                if not self.tracker.can_spend(price):
                    log("AUTO", f"⚠ Daily cap reached (${DAILY_SPEND_CAP}) — stopping")
                    break

                log("AUTO", f"{'[DRY RUN] Would register' if DRY_RUN else 'Registering'} "
                            f"{domain} (score={r['score']}, price=${price})...")

                if DRY_RUN:
                    result = {"success": True, "message": "dry_run"}
                else:
                    result = await register_via_porkbun(session, domain)
                    await asyncio.sleep(1)  # be polite to API

                if result["success"]:
                    self.tracker.record(domain, price)
                    self.db.mark_registered(domain, price)
                    registered.append({**r, "registration": result})
                    self.registered_this_run.append(domain)
                    log("AUTO", f"  ✅ {domain} registered! ${price:.2f} charged")
                else:
                    log("AUTO", f"  ❌ {domain} failed: {result['message']}")

        log("AUTO", f"Run complete — {len(registered)} registered | {self.tracker.summary()}")
        return registered
