"""core/scorer.py — Domain flip potential scoring engine"""

# ── INDUSTRY KEYWORD WEIGHTS ──────────────────────────────────────────────────
# Higher = bigger industry budgets + more motivated buyers
VERTICAL_WEIGHTS = {
    # Finance — biggest buyer budgets
    "kyc": 98, "aml": 95, "underwrite": 93, "audit": 91, "portfolio": 94,
    "compliance": 93, "fraud": 92, "creditrisk": 90, "insurtech": 89,
    "signals": 88, "taxplan": 85, "wealthplan": 82, "rebalance": 78,
    "loanorigination": 77, "actuarial": 88, "clearinghouse": 86,

    # Healthcare — HIPAA complexity = premium pricing
    "triage": 95, "oncology": 94, "pathology": 92, "symptom": 90,
    "imaging": 89, "referral": 86, "careplan": 85, "clinicalnotes": 83,
    "formulary": 78, "discharge": 72, "priorauth": 88, "denialmanagement": 75,
    "radiology": 90, "diagnostics": 91, "ehr": 87,

    # Legal — high willingness to pay
    "contracts": 97, "discovery": 96, "compliance": 93, "paralegal": 91,
    "litigation": 91, "caselaw": 90, "immigration": 89, "deposition": 87,
    "trademark": 85, "legalbrief": 82, "estateplan": 76, "draftlegal": 70,
    "arbitration": 88, "escrow": 85,

    # Education — growing fast
    "tutor": 98, "assessment": 92, "curriculum": 90, "upskill": 91,
    "onboarding": 88, "mcat": 87, "lsat": 86, "gmat": 84, "certify": 83,
    "studyplan": 80, "iep": 79, "gradebook": 75,

    # Universal AI terms — massive demand
    "chat": 99, "search": 99, "build": 97, "generate": 96, "hire": 95,
    "pay": 95, "therapy": 94, "coach": 93, "write": 92, "design": 91,
    "agent": 97, "model": 90, "data": 88, "automate": 89, "analyze": 87,
    "predict": 88, "optimize": 87, "deploy": 85, "train": 84, "monitor": 83,
}

# ── LENGTH SCORING ────────────────────────────────────────────────────────────
def score_length(name: str) -> int:
    """Shorter names = more valuable"""
    n = len(name)
    if n <= 4:  return 30
    if n <= 6:  return 25
    if n <= 8:  return 18
    if n <= 11: return 12
    if n <= 15: return 6
    return 2

# ── PATTERN SCORING ───────────────────────────────────────────────────────────
def score_pattern(name: str) -> int:
    """Single word > compound > hyphenated > random"""
    if name.isalpha():
        return 20  # pure single word
    if name.replace("-", "").isalpha() and "-" in name:
        return 8   # hyphenated
    if name.isalnum():
        return 14  # compound word (no hyphens)
    return 4

# ── MEMORABILITY ─────────────────────────────────────────────────────────────
def score_memorability(name: str) -> int:
    """Penalize hard-to-remember patterns"""
    score = 10
    if any(c.isdigit() for c in name):   score -= 4
    if name.count("-") > 1:              score -= 4
    if len(name) > 12:                   score -= 3
    return max(0, score)

# ── KEYWORD MATCH ─────────────────────────────────────────────────────────────
def score_keywords(name: str) -> tuple[int, str]:
    """Check if name contains any high-value keyword"""
    name_lower = name.lower()
    best_score = 0
    best_kw = None
    for kw, weight in VERTICAL_WEIGHTS.items():
        if kw in name_lower:
            if weight > best_score:
                best_score = weight
                best_kw = kw
    # Scale keyword weight to 0-40 range
    kw_score = int((best_score / 100) * 40) if best_kw else 0
    return kw_score, best_kw

# ── MAIN SCORER ───────────────────────────────────────────────────────────────
class DomainScorer:
    def score(self, domain: str, domain_type: str = "unregistered") -> tuple[int, dict]:
        """
        Returns (total_score 0-100, breakdown dict)
        Breakdown shows what drove the score.
        """
        name = domain.replace(".ai", "").lower()

        length_pts      = score_length(name)
        pattern_pts     = score_pattern(name)
        memory_pts      = score_memorability(name)
        kw_pts, kw_hit  = score_keywords(name)

        # Type bonus — expiring domains are harder to get so slight premium
        type_bonus = {"expiring": 5, "aftermarket": 3, "unregistered": 0}.get(domain_type, 0)

        raw = length_pts + pattern_pts + memory_pts + kw_pts + type_bonus
        total = min(100, raw)

        breakdown = {
            "length":      length_pts,
            "pattern":     pattern_pts,
            "memorability": memory_pts,
            "keyword":     kw_pts,
            "keyword_hit": kw_hit,
            "type_bonus":  type_bonus,
            "total":       total,
        }
        return total, breakdown

    def estimate_value(self, score: int, domain: str) -> tuple[int, int]:
        """Rough flip value estimate based on score"""
        name = domain.replace(".ai", "").lower()
        length = len(name)

        # Base ranges by score tier
        if score >= 95: base_low, base_high = 30000,  200000
        elif score >= 88: base_low, base_high = 8000,   50000
        elif score >= 80: base_low, base_high = 3000,   20000
        elif score >= 70: base_low, base_high = 1000,    8000
        else:             base_low, base_high = 500,     3000

        # Shorter = multiply up
        if length <= 4:  mult = 4.0
        elif length <= 6: mult = 2.0
        elif length <= 8: mult = 1.2
        else:            mult = 1.0

        return int(base_low * mult), int(base_high * mult)
