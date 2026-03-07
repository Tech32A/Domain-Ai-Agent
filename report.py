#!/usr/bin/env python3
"""
report.py — Export results from the domain bot database

Usage:
  python report.py                  # print top 50 to terminal
  python report.py --export csv     # save full CSV
  python report.py --type expiring  # filter by type
  python report.py --min-score 85   # filter by score
"""
import argparse
import json
from datetime import datetime
from pathlib import Path
from core.database import DomainDB

fmt_k = lambda n: f"${n//1000}K" if n and n >= 1000 else f"${n}" if n else "—"

TYPE_LABELS = {
    "unregistered": "🟢 NEW",
    "expiring":     "🟡 DROP",
    "aftermarket":  "🔵 MKT",
}

def print_report(rows, title="DOMAIN FLIP BOT — RESULTS"):
    print(f"\n{'═'*75}")
    print(f"  {title}")
    print(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}  |  {len(rows)} domains")
    print(f"{'═'*75}")
    print(f"  {'#':<4} {'DOMAIN':<28} {'SCR':>3}  {'EST VALUE':>16}  {'TYPE':<10}  {'FIRST SEEN'}")
    print(f"  {'─'*68}")

    for i, r in enumerate(rows, 1):
        type_label = TYPE_LABELS.get(r.get("type",""), "⚪ ???")
        est        = f"{fmt_k(r.get('est_low'))}–{fmt_k(r.get('est_high'))}"
        first_seen = (r.get("first_seen","")[:10] if r.get("first_seen") else "—")
        score_color = "🔴" if r["score"] >= 90 else "🟡" if r["score"] >= 75 else "⚪"
        print(f"  {i:<4} {r['domain']:<28} {score_color}{r['score']:>2}  {est:>16}  {type_label:<10}  {first_seen}")

    print(f"{'═'*75}\n")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--export",    choices=["csv"], help="Export format")
    parser.add_argument("--type",      choices=["unregistered","expiring","aftermarket"])
    parser.add_argument("--min-score", type=int, default=70)
    parser.add_argument("--limit",     type=int, default=50)
    args = parser.parse_args()

    db   = DomainDB()
    rows = db.get_all(min_score=args.min_score, domain_type=args.type)[:args.limit]

    if not rows:
        print("No results found. Run `python bot.py` first.")
        return

    print_report(rows)

    # Stats
    stats = db.get_stats()
    print(f"  DB STATS: total={stats['total']}  unregistered={stats['unregistered']}  "
          f"expiring={stats['expiring']}  aftermarket={stats['aftermarket']}")
    print(f"           avg_score={round(stats['avg_score'] or 0,1)}  "
          f"max_score={stats['max_score']}\n")

    if args.export == "csv":
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        path = f"ai_domain_results_{timestamp}.csv"
        db.export_csv(path)
        print(f"  ✅ Exported to: {path}\n")

if __name__ == "__main__":
    main()
