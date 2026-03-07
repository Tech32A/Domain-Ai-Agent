"""
pricing/trends_scorer.py — Google Trends momentum scoring

Adds a trend momentum layer to domain scoring:
- Rising keyword = score bonus (up to +15 points)
- Falling keyword = score penalty (up to -10 points)
- Stable = no change

Uses pytrends (unofficial Google Trends API — free, no key needed).
Falls back to keyword heuristics if pytrends is unavailable.

Install: pip install pytrends
"""

import json
import time
import asyncio
from pathlib import Path
from core.logger import log

TRENDS_CACHE = Path(__file__).parent.parent / "data" / "trends_cache.json"
CACHE_TTL    = 86400  # 24 hours — trends don't change that fast


# ── TREND CLASSIFIER ──────────────────────────────────────────────────────────
def classify_trend(values: list[int]) -> tuple[str, int]:
    """
    Given a list of weekly interest values (0-100),
    returns (direction, score_delta).
    direction: "rising" | "stable" | "falling"
    score_delta: -10 to +15
    """
    if not values or len(values) < 4:
        return "stable", 0

    recent = sum(values[-4:]) / 4   # last month avg
    older  = sum(values[-12:-4]) / 8 if len(values) >= 12 else sum(values[:-4]) / max(len(values[:-4]),1)

    if older == 0:
        return "rising", 10

    change_pct = ((recent - older) / older) * 100

    if change_pct >= 50:   return "rising",  15
    if change_pct >= 20:   return "rising",  10
    if change_pct >= 5:    return "rising",   5
    if change_pct <= -30:  return "falling", -10
    if change_pct <= -15:  return "falling",  -5
    return "stable", 0


# ── CACHE LAYER ───────────────────────────────────────────────────────────────
def load_cache() -> dict:
    if TRENDS_CACHE.exists():
        try:
            data = json.loads(TRENDS_CACHE.read_text())
            if time.time() - data.get("updated_at", 0) < CACHE_TTL:
                return data.get("keywords", {})
        except Exception:
            pass
    return {}

def save_cache(keywords: dict):
    TRENDS_CACHE.parent.mkdir(exist_ok=True)
    TRENDS_CACHE.write_text(json.dumps({
        "updated_at": time.time(),
        "keywords":   keywords,
    }, indent=2))


# ── PYTRENDS FETCHER ──────────────────────────────────────────────────────────
async def fetch_trends_pytrends(keywords: list[str]) -> dict:
    """Fetch Google Trends data via pytrends"""
    try:
        from pytrends.request import TrendReq
    except ImportError:
        log("TREND", "  pytrends not installed — run: pip install pytrends")
        return {}

    results = {}
    # Pytrends is synchronous — run in thread pool
    loop = asyncio.get_event_loop()

    def _fetch():
        pt = TrendReq(hl="en-US", tz=360, timeout=(10, 25), retries=2, backoff_factor=0.5)
        out = {}
        # Batch in groups of 5 (pytrends limit)
        for i in range(0, len(keywords), 5):
            batch = keywords[i:i+5]
            try:
                pt.build_payload(batch, cat=0, timeframe="today 12-m", geo="", gprop="")
                df = pt.interest_over_time()
                if df.empty:
                    continue
                for kw in batch:
                    if kw in df.columns:
                        values = df[kw].tolist()
                        direction, delta = classify_trend(values)
                        out[kw] = {
                            "direction": direction,
                            "delta":     delta,
                            "peak":      max(values),
                            "recent":    round(sum(values[-4:])/4),
                        }
                time.sleep(2)  # be polite to Google
            except Exception as e:
                log("TREND", f"  Batch error: {str(e)[:60]}")
                continue
        return out

    try:
        results = await loop.run_in_executor(None, _fetch)
    except Exception as e:
        log("TREND", f"  pytrends fetch failed: {str(e)[:60]}")

    return results


# ── HEURISTIC FALLBACK ────────────────────────────────────────────────────────
# When pytrends fails, use keyword knowledge as a fallback signal
KNOWN_RISING = {
    "agent","agentic","workflow","automate","copilot","voice","multimodal",
    "rag","embedding","finetune","kyc","compliance","fraud","triage","oncology",
    "discovery","paralegal","upskill","certify","assessment","underwrite",
}
KNOWN_FALLING = {
    "chatbot","nft","metaverse","blockchain","crypto","web3","dao",
}

def heuristic_trend(keyword: str) -> tuple[str, int]:
    kw = keyword.lower()
    for r in KNOWN_RISING:
        if r in kw: return "rising", 8
    for f in KNOWN_FALLING:
        if f in kw: return "falling", -8
    return "stable", 0


# ── MAIN TRENDS SCORER ────────────────────────────────────────────────────────
class TrendsScorer:
    def __init__(self):
        self.cache = load_cache()

    async def enrich(self, keywords: list[str]) -> dict[str, dict]:
        """
        Fetch trend data for a list of keywords.
        Returns dict: keyword → {direction, delta, peak, recent}
        """
        # Split into cached vs needs fetching
        cached   = {kw: self.cache[kw] for kw in keywords if kw in self.cache}
        to_fetch = [kw for kw in keywords if kw not in self.cache]

        if to_fetch:
            log("TREND", f"Fetching Google Trends for {len(to_fetch)} keywords...")
            fetched = await fetch_trends_pytrends(to_fetch)

            # Fill gaps with heuristics
            for kw in to_fetch:
                if kw not in fetched:
                    direction, delta = heuristic_trend(kw)
                    fetched[kw] = {
                        "direction": direction,
                        "delta":     delta,
                        "peak":      None,
                        "recent":    None,
                        "source":    "heuristic",
                    }

            self.cache.update(fetched)
            save_cache(self.cache)

        all_results = {**cached, **{kw: self.cache.get(kw, {"direction":"stable","delta":0}) for kw in to_fetch}}
        return all_results

    def score_domain(self, domain: str, trend_data: dict) -> tuple[int, str]:
        """
        Apply trend delta to domain score.
        Returns (delta, direction_label)
        """
        name = domain.replace(".ai","").replace(".io","").replace(".com","").lower()

        # Find best matching keyword in trend data
        best_delta     = 0
        best_direction = "stable"

        for kw, data in trend_data.items():
            if kw.lower() in name:
                delta = data.get("delta", 0)
                if abs(delta) > abs(best_delta):
                    best_delta     = delta
                    best_direction = data.get("direction", "stable")

        # Fallback to heuristic
        if best_delta == 0:
            best_direction, best_delta = heuristic_trend(name)

        return best_delta, best_direction

    async def enrich_results(self, results: list[dict]) -> list[dict]:
        """Add trend scoring to a list of domain results"""
        if not results:
            return results

        # Extract unique keywords from domain names
        keywords = set()
        for r in results:
            name = r["domain"].replace(".ai","").replace(".io","").replace(".com","").lower()
            # Split compound words roughly
            import re
            words = re.findall(r'[a-z]{3,}', name)
            keywords.update(words)

        trend_data = await self.enrich(list(keywords)[:50])  # cap at 50 keywords

        for r in results:
            delta, direction = self.score_domain(r["domain"], trend_data)
            r["trend_direction"] = direction
            r["trend_delta"]     = delta
            r["trend_score"]     = r.get("score", 0) + delta
            # Clamp to 0-100
            r["trend_score"]     = max(0, min(100, r["trend_score"]))

        # Re-sort by trend score
        results.sort(key=lambda x: -x.get("trend_score", x.get("score", 0)))
        log("TREND", f"Trend scoring complete — {len(results)} domains enriched")
        return results
