"""
dashboard/api.py — FastAPI backend for the web dashboard

Exposes the SQLite database and bot controls via a REST API.
The React frontend connects to this.

Run locally:
  pip install fastapi uvicorn
  python dashboard/api.py

Then open: http://localhost:8000
"""

import os
import json
import asyncio
from datetime import datetime, date
from pathlib import Path
from typing import Optional

try:
    from fastapi import FastAPI, HTTPException, BackgroundTasks
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
    from fastapi.middleware.cors import CORSMiddleware
    import uvicorn
except ImportError:
    print("Run: pip install fastapi uvicorn")
    exit(1)

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.database import DomainDB
from core.logger import log
from autoregister.auto_register import SpendTracker

app = FastAPI(title="AI Domain Flip Bot", version="4.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

db      = DomainDB()
tracker = SpendTracker()

# ── DOMAIN ENDPOINTS ──────────────────────────────────────────────────────────
@app.get("/api/domains")
async def get_domains(
    min_score:   int = 0,
    domain_type: Optional[str] = None,
    vertical:    Optional[str] = None,
    limit:       int = 100,
    sort:        str = "score",
):
    rows = db.get_all(min_score=min_score, domain_type=domain_type)

    if vertical:
        from core.scorer import VERTICAL_WEIGHTS
        rows = [r for r in rows if any(
            kw in r["domain"].lower()
            for kw in VERTICAL_WEIGHTS
        )]

    if sort == "score":
        rows.sort(key=lambda x: -x.get("score", 0))
    elif sort == "date":
        rows.sort(key=lambda x: x.get("first_seen", ""), reverse=True)
    elif sort == "value":
        rows.sort(key=lambda x: -(x.get("est_high", 0) or 0))

    return {"domains": rows[:limit], "total": len(rows)}


@app.get("/api/domains/{domain}")
async def get_domain(domain: str):
    rows = db.get_all()
    match = next((r for r in rows if r["domain"] == domain), None)
    if not match:
        raise HTTPException(status_code=404, detail="Domain not found")
    return match


@app.get("/api/stats")
async def get_stats():
    stats = db.get_stats()
    spend = {
        "today":     tracker.spent_today,
        "cap":       float(os.getenv("DAILY_SPEND_CAP", "50")),
        "remaining": tracker.remaining,
    }
    return {**stats, "spend": spend, "timestamp": datetime.now().isoformat()}


@app.get("/api/top")
async def get_top(limit: int = 20, min_score: int = 80):
    rows = db.get_all(min_score=min_score)[:limit]
    return {"domains": rows, "count": len(rows)}


@app.get("/api/backorders")
async def get_backorders():
    from backorder.dropcatch import BackorderTracker
    bt = BackorderTracker()
    return {"backorders": bt.get_all()}


@app.get("/api/trends/breakouts")
async def get_breakouts():
    rows = db.get_all()
    breakouts = [r for r in rows if r.get("trend_label", "").startswith("🚀")]
    return {"breakouts": breakouts, "count": len(breakouts)}


# ── BOT CONTROL ENDPOINTS ─────────────────────────────────────────────────────
_scan_running = False

@app.post("/api/scan/trigger")
async def trigger_scan(background_tasks: BackgroundTasks, mode: str = "full"):
    global _scan_running
    if _scan_running:
        return {"status": "already_running", "message": "Scan already in progress"}

    async def run_scan():
        global _scan_running
        _scan_running = True
        try:
            from bot import DomainFlipBot
            bot = DomainFlipBot(mode=mode)
            await bot.run()
        finally:
            _scan_running = False

    background_tasks.add_task(run_scan)
    return {"status": "started", "mode": mode}


@app.get("/api/scan/status")
async def scan_status():
    return {"running": _scan_running}


@app.post("/api/register/{domain}")
async def register_domain(domain: str):
    """Manually trigger registration of a specific domain"""
    from autoregister.auto_register import register_via_porkbun
    import aiohttp
    async with aiohttp.ClientSession() as session:
        result = await register_via_porkbun(session, domain)
    if result["success"]:
        db.mark_registered(domain, 0)
    return result


@app.get("/api/export/csv")
async def export_csv():
    """Download full database as CSV"""
    path = "/tmp/domain_export.csv"
    db.export_csv(path)
    return FileResponse(path, filename=f"domains_{date.today()}.csv", media_type="text/csv")


# ── SERVE FRONTEND ────────────────────────────────────────────────────────────
FRONTEND_DIR = Path(__file__).parent / "static"

@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    index = FRONTEND_DIR / "index.html"
    if index.exists():
        return index.read_text()
    return HTMLResponse("<h1>AI Domain Bot API</h1><p>Frontend not built yet. See /docs</p>")


if __name__ == "__main__":
    port = int(os.getenv("DASHBOARD_PORT", "8000"))
    log("DASH", f"Starting dashboard at http://localhost:{port}")
    uvicorn.run("dashboard.api:app", host="0.0.0.0", port=port, reload=True)
