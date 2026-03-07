"""generators/keyword_generator.py — Semantic keyword combination engine"""
import itertools
import random

# ── MASTER KEYWORD LISTS BY VERTICAL ─────────────────────────────────────────

HEALTHCARE = {
    "actions":  ["triage","diagnose","monitor","detect","predict","analyze","screen",
                 "prescribe","refer","assess","schedule","discharge","authorize","code"],
    "nouns":    ["patient","clinical","health","medical","care","therapy","imaging",
                 "pathology","oncology","radiology","pharmacy","ehr","notes","records",
                 "prior","denial","formulary","referral","symptom","claim","billing"],
    "roles":    ["doctor","nurse","provider","specialist","clinician","pharmacist"],
    "outcomes": ["outcomes","safety","compliance","quality","efficiency","access"],
}

LEGAL = {
    "actions":  ["draft","review","analyze","research","file","argue","negotiate",
                 "discover","depose","audit","comply","trademark","patent","mediate"],
    "nouns":    ["contract","case","brief","motion","discovery","deposition","evidence",
                 "compliance","immigration","litigation","arbitration","trademark","ip",
                 "estate","will","trust","paralegal","counsel","verdict","settlement"],
    "roles":    ["attorney","lawyer","counsel","paralegal","judge","clerk"],
    "outcomes": ["resolution","clarity","strategy","defense","justice","risk"],
}

FINANCE = {
    "actions":  ["underwrite","audit","score","predict","detect","optimize","balance",
                 "hedge","trade","allocate","rebalance","comply","verify","assess"],
    "nouns":    ["kyc","aml","fraud","credit","risk","portfolio","wealth","tax","loan",
                 "insurance","signal","compliance","audit","actuary","clearing","escrow",
                 "ledger","budget","forecast","cashflow","invoice","payroll","cap"],
    "roles":    ["advisor","analyst","trader","actuary","underwriter","auditor"],
    "outcomes": ["returns","growth","protection","efficiency","accuracy","trust"],
}

EDUCATION = {
    "actions":  ["tutor","assess","grade","learn","train","certify","upskill","coach",
                 "mentor","evaluate","personalize","onboard","study","test","quiz"],
    "nouns":    ["curriculum","student","course","exam","skill","credential","degree",
                 "lesson","feedback","rubric","iep","lms","gradebook","assessment",
                 "mcat","lsat","gmat","sat","act","board","bar","cpa","cfa"],
    "roles":    ["teacher","instructor","tutor","student","learner","trainee"],
    "outcomes": ["mastery","progress","retention","performance","achievement","growth"],
}

# Universal high-value single words
UNIVERSAL_SINGLES = [
    "chat","search","build","generate","hire","pay","write","design","agent",
    "model","data","automate","analyze","predict","optimize","deploy","train",
    "monitor","audit","coach","therapy","assist","pilot","copilot","workflow",
    "insight","signal","brief","draft","verify","review","summarize","translate",
    "classify","extract","parse","score","rank","match","route","schedule",
]

# High-value prefixes and suffixes
PREFIXES = ["auto","smart","deep","fast","clear","true","open","meta","hyper","ultra"]
SUFFIXES = ["pro","hub","io","ops","hq","lab","core","base","flow","sync","link","ai"]


class KeywordGenerator:
    def generate(self, limit: int = 300) -> list[str]:
        domains = set()

        # 1. Single universal words
        for word in UNIVERSAL_SINGLES:
            domains.add(f"{word}.ai")

        # 2. Single-word vertical keywords
        for vertical in [HEALTHCARE, LEGAL, FINANCE, EDUCATION]:
            for category in vertical.values():
                for word in category:
                    if len(word) <= 12:
                        domains.add(f"{word}.ai")

        # 3. Action + Noun compounds (no separator)
        for vertical in [HEALTHCARE, LEGAL, FINANCE, EDUCATION]:
            combos = list(itertools.product(
                vertical["actions"][:8],
                vertical["nouns"][:8]
            ))
            random.shuffle(combos)
            for action, noun in combos[:30]:
                compound = f"{action}{noun}"
                if 6 <= len(compound) <= 16:
                    domains.add(f"{compound}.ai")

        # 4. Prefix + keyword combos
        all_keywords = (
            HEALTHCARE["nouns"] + LEGAL["nouns"] +
            FINANCE["nouns"] + EDUCATION["nouns"]
        )
        for prefix in PREFIXES:
            for kw in random.sample(all_keywords, min(8, len(all_keywords))):
                compound = f"{prefix}{kw}"
                if len(compound) <= 14:
                    domains.add(f"{compound}.ai")

        # 5. Keyword + suffix combos
        for kw in random.sample(all_keywords, min(15, len(all_keywords))):
            for suffix in random.sample(SUFFIXES, 3):
                compound = f"{kw}{suffix}"
                if len(compound) <= 14:
                    domains.add(f"{compound}.ai")

        # 6. Action + outcome (e.g. "predictoutcomes" → too long, filter)
        for vertical in [HEALTHCARE, FINANCE]:
            for action in vertical["actions"][:5]:
                for outcome in vertical["outcomes"][:4]:
                    compound = f"{action}{outcome}"
                    if len(compound) <= 15:
                        domains.add(f"{compound}.ai")

        result = list(domains)
        random.shuffle(result)
        return result[:limit]
