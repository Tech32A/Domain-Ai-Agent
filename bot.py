#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════╗
║           AI DOMAIN FLIP BOT — Main Orchestrator            ║
║  Hunts unregistered + expiring + underpriced .ai domains    ║
║  Generates ideas via AI + VC scraping + keyword combos      ║
║  Scores, ranks, alerts — built to scale to web later        ║
╚══════════════════════════════════════════════════════════════╝

QUICK START:
  pip install -r requirements.txt
  cp .env.template .env        # add your API keys
  python bot.py                # full scan
  python bot.py --mode fast    # quick unregistered check only
  python bot.py --mode expiring # focus on dropping domains
  python bot.py --mode market  # aftermarket underpriced scan
"""

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from core.logger import log, banner
from core.database import DomainDB
from core.scorer import DomainScorer
from generators.keyword_generator import KeywordGenerator
from generators.ai_generator import AIGenerator
from generators.vc_scraper import VCScraper
from hunters.availability_hunter import AvailabilityHunter
from hunters.expiry_hunter import ExpiryHunter
from hunters.market_hunter import MarketHunter
from alerts.notifier import Notifier


# ── CONFIG ────────────────────────────────────────────────────────────────────
SCORE_THRESHOLD  = int(os.getenv("SCORE_THRESHOLD", "70"))     # min score to save
ALERT_THRESHOLD  = int(os.getenv("ALERT_THRESHOLD", "85"))     # min score to alert
SCAN_INTERVAL_HR = int(os.getenv("SCAN_INTERVAL_HR", "6"))     # hours between auto-scans
MAX_DOMAINS_PER_RUN = int(os.getenv("MAX_DOMAINS_PER_RUN", "200"))


# ── ORCHESTRATOR ──────────────────────────────────────────────────────────────
class DomainFlipBot:
    def __init__(self, mode="full"):
        self.mode     = mode
        self.db       = DomainDB()
        self.scorer   = DomainScorer()
        self.notifier = Notifier()
        self.results  = []

    async def generate_candidates(self) -> list[str]:
        """Pull domain candidates from all three generators"""
        candidates = set()

        # 1. Keyword combinations (always runs)
        log("GEN", "Building keyword combinations...")
        kg = KeywordGenerator()
        kw_domains = kg.generate(limit=300)
        candidates.update(kw_domains)
        log("GEN", f"  → {len(kw_domains)} keyword combos generated")

        # 2. AI-generated names
        if os.getenv("ANTHROPIC_API_KEY"):
            log("GEN", "Running AI domain generator...")
            ai = AIGenerator()
            ai_domains = await ai.generate(limit=100)
            candidates.update(ai_domains)
            log("GEN", f"  → {len(ai_domains)} AI-generated names added")
        else:
            log("WARN", "No ANTHROPIC_API_KEY — skipping AI generation")

        # 3. VC news scraper
        log("GEN", "Scraping VC/funding news for trending keywords...")
        vc = VCScraper()
        vc_domains = await vc.generate(limit=100)
        candidates.update(vc_domains)
        log("GEN", f"  → {len(vc_domains)} VC-trend domains added")

        total = list(candidates)[:MAX_DOMAINS_PER_RUN]
        log("GEN", f"Total candidates: {len(total)}")
        return total

    async def hunt_unregistered(self, candidates: list[str]):
        """Check which candidates are available to register fresh"""
        log("HUNT", "Checking unregistered availability...")
        hunter = AvailabilityHunter()
        available = await hunter.check_bulk(candidates)
        log("HUNT", f"  → {len(available)} unregistered domains found")
        return [{"domain": d["domain"], "type": "unregistered", **d} for d in available]

    async def hunt_expiring(self):
        """Scrape drop lists for expiring .ai domains"""
        log("HUNT", "Scanning expiring/dropping .ai domains...")
        hunter = ExpiryHunter()
        expiring = await hunter.scan()
        log("HUNT", f"  → {len(expiring)} expiring domains found")
        return [{"domain": d["domain"], "type": "expiring", **d} for d in expiring]

    async def hunt_market(self):
        """Find underpriced .ai listings on Sedo/Afternic"""
        log("HUNT", "Scanning aftermarket for underpriced listings...")
        hunter = MarketHunter()
        listings = await hunter.scan()
        log("HUNT", f"  → {len(listings)} aftermarket listings found")
        return [{"domain": d["domain"], "type": "aftermarket", **d} for d in listings]

    def score_and_filter(self, raw_results: list[dict]) -> list[dict]:
        """Score every result, filter below threshold, sort by score"""
        scored = []
        for item in raw_results:
            score, breakdown = self.scorer.score(item["domain"], item.get("type", "unregistered"))
            if score >= SCORE_THRESHOLD:
                item["score"]     = score
                item["breakdown"] = breakdown
                item["est_low"], item["est_high"] = self.scorer.estimate_value(score, item["domain"])
                scored.append(item)

        scored.sort(key=lambda x: -x["score"])
        return scored

    def save_results(self, results: list[dict]):
        """Persist results to SQLite DB"""
        for r in results:
            self.db.upsert(r)
        log("DB", f"Saved {len(results)} results to database")

    def alert_on_hot_finds(self, results: list[dict]):
        """Send alerts for high-score finds"""
        hot = [r for r in results if r["score"] >= ALERT_THRESHOLD]
        if hot:
            log("ALERT", f"🔥 {len(hot)} HIGH-VALUE domains found — alerting...")
            self.notifier.send(hot)
        else:
            log("ALERT", "No domains above alert threshold this run")

    def print_report(self, results: list[dict]):
        """Pretty-print top finds to terminal"""
        print("\n" + "═"*65)
        print(f"  TOP FINDS — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        print("═"*65)

        for i, r in enumerate(results[:20], 1):
            type_tag = {"unregistered": "🟢 NEW", "expiring": "🟡 DROP", "aftermarket": "🔵 MKT"}.get(r["type"], "⚪")
            price_str = f"${r.get('market_price','?')}" if r["type"] == "aftermarket" else f"~${r.get('reg_price', 80)}/yr"
            print(f"  {i:02d}. {r['domain']:<30} score={r['score']:3d}  "
                  f"est=${r['est_low']//1000}K–${r['est_high']//1000}K  "
                  f"{type_tag}  {price_str}")

        print("═"*65)
        print(f"  Total saved: {len(results)}  |  DB: domainbot/data/domains.db")
        print(f"  Run `python report.py` for full CSV export")
        print("═"*65 + "\n")

    async def run(self):
        banner()
        log("BOT", f"Starting scan — mode={self.mode}")
        start = time.time()

        all_results = []

        if self.mode in ("full", "fast"):
            candidates = await self.generate_candidates()
            unreg = await self.hunt_unregistered(candidates)
            all_results.extend(unreg)

        if self.mode in ("full", "expiring"):
            expiring = await self.hunt_expiring()
            all_results.extend(expiring)

        if self.mode in ("full", "market"):
            market = await self.hunt_market()
            all_results.extend(market)

        log("BOT", f"Raw results: {len(all_results)} — scoring and filtering...")
        scored = self.score_and_filter(all_results)

        self.save_results(scored)
        self.alert_on_hot_finds(scored)
        self.print_report(scored)

        elapsed = round(time.time() - start, 1)
        log("BOT", f"Scan complete in {elapsed}s — {len(scored)} domains above threshold")


# ── SCHEDULER (for continuous mode) ──────────────────────────────────────────
async def run_scheduled(mode):
    while True:
        bot = DomainFlipBot(mode=mode)
        await bot.run()
        log("SCHED", f"Next scan in {SCAN_INTERVAL_HR} hours...")
        await asyncio.sleep(SCAN_INTERVAL_HR * 3600)


# ── ENTRY POINT ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI Domain Flip Bot")
    parser.add_argument("--mode", choices=["full","fast","expiring","market"], default="full",
                        help="Scan mode (default: full)")
    parser.add_argument("--continuous", action="store_true",
                        help="Run on a schedule continuously")
    args = parser.parse_args()

    if args.continuous:
        asyncio.run(run_scheduled(args.mode))
    else:
        asyncio.run(DomainFlipBot(mode=args.mode).run())
