# 🤖 AI Domain Flip Bot

Hunt, score, and alert on high-value `.ai` domains across three strategies:
**unregistered** (never taken) · **expiring** (dropping back to market) · **aftermarket** (underpriced listings)

---

## Architecture

```
domainbot/
├── bot.py                  ← Main orchestrator (run this)
├── report.py               ← Export & view results
├── requirements.txt
├── .env.template           ← Copy to .env, add your keys
│
├── generators/             ← HOW domains are discovered
│   ├── keyword_generator.py   Semantic keyword combos (no API needed)
│   ├── ai_generator.py        Claude AI generates brandable names
│   └── vc_scraper.py          Scrapes VC/funding news for trends
│
├── hunters/                ← WHERE availability is checked
│   ├── availability_hunter.py  GoDaddy + WhoisXML consensus check
│   ├── expiry_hunter.py        Drop lists + watchlist WHOIS expiry
│   └── market_hunter.py        Sedo, Afternic, Dan.com underpriced scan
│
├── core/
│   ├── scorer.py           ← Flip potential scoring engine (0–100)
│   ├── database.py         ← SQLite persistence
│   └── logger.py           ← Colored terminal output
│
├── alerts/
│   └── notifier.py         ← Email + SMS alerts
│
└── data/
    └── domains.db          ← Auto-created SQLite database
```

---

## Setup

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure API keys
cp .env.template .env
# Edit .env with your keys

# 3. Run a full scan
python bot.py

# 4. View results
python report.py
python report.py --export csv
```

---

## Run Modes

| Command | What it does |
|---|---|
| `python bot.py` | Full scan — all three strategies |
| `python bot.py --mode fast` | Unregistered domains only (fastest) |
| `python bot.py --mode expiring` | Drop list + watchlist only |
| `python bot.py --mode market` | Aftermarket underpriced only |
| `python bot.py --continuous` | Runs every N hours (set SCAN_INTERVAL_HR in .env) |

---

## Scoring System

Every domain is scored 0–100 based on:

| Factor | Max Points | Notes |
|---|---|---|
| Keyword match | 40 | Industry keyword weight × relevance |
| Length | 30 | Shorter = more valuable |
| Pattern | 20 | Single word > compound > hyphenated |
| Memorability | 10 | Penalizes numbers, double hyphens |
| Type bonus | +5 | Expiring domains get slight boost |

**Alert threshold default: 85** — change in `.env`

---

## API Keys Needed

| Key | Where to get | Required? |
|---|---|---|
| GoDaddy API key + secret | developer.godaddy.com/keys | ✅ Yes |
| WhoisXML API key | whoisxmlapi.com | ✅ Yes |
| Anthropic API key | console.anthropic.com | Recommended |
| Namecheap API | namecheap.com/support/api | Optional |
| Gmail App Password | myaccount.google.com/apppasswords | For email alerts |
| Twilio credentials | twilio.com | For SMS alerts |

---

## Scaling to Web (Future)

This bot is built to scale. When you're ready:

1. **API layer**: Wrap `bot.py` with FastAPI — expose `/scan`, `/results`, `/stats` endpoints
2. **Scheduler**: Replace `asyncio.sleep` loop with Celery + Redis for robust scheduling
3. **Database**: Swap SQLite for PostgreSQL — schema is already compatible
4. **Frontend**: Connect the React dashboard (domain-live-dashboard.jsx) to the API
5. **Deploy**: Docker → Railway / Fly.io / AWS EC2

The folder structure already maps 1:1 to a production web service.

---

## Tips for Maximizing Finds

- Run `--mode fast` every 2–3 hours (cheap, catches new registrations)
- Run `--mode expiring` daily (drop lists refresh overnight)
- Run `--mode market` weekly (aftermarket moves slower)
- Set `ALERT_THRESHOLD=80` to catch more opportunities early
- The `data/domains.db` grows over time — run `report.py` to see trends
