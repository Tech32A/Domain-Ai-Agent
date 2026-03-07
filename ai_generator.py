"""core/database.py — SQLite persistence layer"""
import sqlite3
import json
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "domains.db"

class DomainDB:
    def __init__(self):
        DB_PATH.parent.mkdir(exist_ok=True)
        self.conn = sqlite3.connect(DB_PATH)
        self._init_schema()

    def _init_schema(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS domains (
                domain          TEXT PRIMARY KEY,
                type            TEXT,
                score           INTEGER,
                est_low         INTEGER,
                est_high        INTEGER,
                reg_price       REAL,
                market_price    REAL,
                expiry_date     TEXT,
                registrar       TEXT,
                breakdown       TEXT,
                first_seen      TEXT,
                last_checked    TEXT,
                alerted         INTEGER DEFAULT 0,
                status          TEXT DEFAULT 'available'
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS scan_runs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at  TEXT,
                mode        TEXT,
                found_count INTEGER,
                alert_count INTEGER
            )
        """)
        self.conn.commit()

    def upsert(self, r: dict):
        now = datetime.now().isoformat()
        existing = self.conn.execute(
            "SELECT first_seen FROM domains WHERE domain=?", (r["domain"],)
        ).fetchone()
        first_seen = existing[0] if existing else now

        self.conn.execute("""
            INSERT OR REPLACE INTO domains
            (domain, type, score, est_low, est_high, reg_price, market_price,
             expiry_date, registrar, breakdown, first_seen, last_checked, status)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            r["domain"],
            r.get("type", "unregistered"),
            r.get("score", 0),
            r.get("est_low", 0),
            r.get("est_high", 0),
            r.get("reg_price"),
            r.get("market_price"),
            r.get("expiry_date"),
            r.get("registrar"),
            json.dumps(r.get("breakdown", {})),
            first_seen,
            now,
            r.get("status", "available")
        ))
        self.conn.commit()

    def get_all(self, min_score=0, domain_type=None) -> list[dict]:
        query = "SELECT * FROM domains WHERE score >= ?"
        params = [min_score]
        if domain_type:
            query += " AND type = ?"
            params.append(domain_type)
        query += " ORDER BY score DESC"
        rows = self.conn.execute(query, params).fetchall()
        cols = [d[0] for d in self.conn.execute(query, params).description] if rows else []
        # Re-fetch with description
        cur = self.conn.execute(query, params)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def mark_alerted(self, domain: str):
        self.conn.execute("UPDATE domains SET alerted=1 WHERE domain=?", (domain,))
        self.conn.commit()

    def get_stats(self) -> dict:
        cur = self.conn.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN type='unregistered' THEN 1 ELSE 0 END) as unregistered,
                SUM(CASE WHEN type='expiring' THEN 1 ELSE 0 END) as expiring,
                SUM(CASE WHEN type='aftermarket' THEN 1 ELSE 0 END) as aftermarket,
                AVG(score) as avg_score,
                MAX(score) as max_score
            FROM domains
        """)
        row = cur.fetchone()
        cols = [d[0] for d in cur.description]
        return dict(zip(cols, row))

    def export_csv(self, path: str):
        import csv
        rows = self.get_all()
        if not rows:
            return
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)

    def mark_registered(self, domain: str, price: float):
        self.conn.execute(
            "UPDATE domains SET status='registered', reg_price=? WHERE domain=?",
            (price, domain)
        )
        self.conn.commit()
