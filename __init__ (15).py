"""
outreach/buyer_matcher.py — Finds likely buyers + generates outreach emails

For each domain found, this module:
1. Identifies the industry vertical from the domain name
2. Searches for funded startups in that space (via Crunchbase + LinkedIn hints)
3. Generates a personalized cold outreach email per domain
4. Outputs ready-to-send email drafts

Uses Claude API to write natural, non-spammy outreach emails.
"""

import os
import re
import json
import asyncio
import aiohttp
from core.logger import log

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
SENDER_NAME       = os.getenv("OUTREACH_SENDER_NAME", "")
SENDER_EMAIL      = os.getenv("OUTREACH_SENDER_EMAIL", "")

# Vertical → industry descriptor for email context
VERTICAL_CONTEXT = {
    # Healthcare
    "triage":    ("healthcare AI", "hospitals and urgent care networks"),
    "oncology":  ("oncology AI", "cancer treatment centers and biotech companies"),
    "pathology": ("diagnostic AI", "pathology labs and digital health companies"),
    "imaging":   ("medical imaging AI", "radiology departments and healthtech startups"),
    "careplan":  ("care management AI", "health systems and care coordination platforms"),
    "priorauth": ("revenue cycle AI", "healthcare billing companies and health plans"),
    "symptom":   ("patient-facing AI", "digital health apps and telehealth companies"),
    "referral":  ("care navigation AI", "health networks and patient engagement platforms"),
    # Legal
    "contracts": ("contract AI", "CLM platforms and corporate legal departments"),
    "discovery": ("legal discovery AI", "litigation support firms and BigLaw"),
    "paralegal": ("legal ops AI", "law firms and legal technology companies"),
    "compliance":("compliance AI",  "RegTech companies and corporate legal teams"),
    "immigration":("immigration AI", "immigration law firms and HR platforms"),
    "trademark": ("IP management AI","intellectual property firms and brand agencies"),
    "caselaw":   ("legal research AI","law schools and research-focused law firms"),
    # Finance
    "kyc":       ("KYC/AML AI",     "banks, fintechs and compliance vendors"),
    "audit":     ("audit AI",       "accounting firms and CFO software companies"),
    "underwrite":("underwriting AI","insurance carriers and lending platforms"),
    "fraud":     ("fraud detection AI","payment processors and financial institutions"),
    "portfolio": ("portfolio AI",   "wealth management firms and robo-advisors"),
    "creditrisk":("credit risk AI", "lenders and credit bureau companies"),
    "signals":   ("trading signals AI","hedge funds and quantitative trading firms"),
    # Education
    "tutor":     ("AI tutoring",    "EdTech companies and school districts"),
    "assessment":("assessment AI",  "test publishers and learning management platforms"),
    "curriculum":("curriculum AI",  "curriculum companies and school systems"),
    "upskill":   ("workforce AI",   "corporate L&D platforms and HR tech companies"),
    "certify":   ("credentialing AI","professional certification bodies and HR platforms"),
    "mcat":      ("test prep AI",   "medical school prep companies and pre-med platforms"),
    "lsat":      ("test prep AI",   "law school prep companies and bar exam providers"),
}

def get_vertical_context(domain: str) -> tuple[str, str]:
    """Return (industry, buyer_types) for a domain"""
    name = domain.replace(".ai","").replace(".io","").replace(".com","").lower()
    for kw, (industry, buyers) in VERTICAL_CONTEXT.items():
        if kw in name:
            return industry, buyers
    return "AI technology", "AI startups and technology companies"


# ── CRUNCHBASE SEARCH ─────────────────────────────────────────────────────────
async def find_funded_companies(session: aiohttp.ClientSession, vertical: str, limit: int = 5) -> list[dict]:
    """
    Search Crunchbase for recently funded companies in a vertical.
    Uses the free/public search endpoint — no API key required.
    """
    companies = []
    try:
        # Crunchbase autocomplete — free, no auth
        url = "https://www.crunchbase.com/v4/data/autocompletes"
        params = {"query": vertical, "collection_ids": "organizations", "limit": limit}
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Accept": "application/json",
            "Referer": "https://www.crunchbase.com",
        }
        async with session.get(url, params=params, headers=headers,
                               timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status == 200:
                data = await resp.json()
                for entity in data.get("entities", [])[:limit]:
                    props = entity.get("properties", {})
                    companies.append({
                        "name":       props.get("identifier", {}).get("value", ""),
                        "short_desc": props.get("short_description", ""),
                        "location":   props.get("location_identifiers", [{}])[0].get("value", "") if props.get("location_identifiers") else "",
                        "cb_url":     f"https://crunchbase.com/organization/{props.get('identifier', {}).get('permalink', '')}",
                    })
    except Exception as e:
        log("OUTREACH", f"  Crunchbase search failed: {str(e)[:60]}")

    return companies


# ── AI EMAIL WRITER ───────────────────────────────────────────────────────────
async def generate_outreach_email(
    domain: str,
    industry: str,
    buyer_types: str,
    company_name: str = "",
    est_low: int = 0,
    est_high: int = 0,
) -> str:
    """Use Claude to write a natural, non-spammy domain outreach email"""

    if not ANTHROPIC_API_KEY:
        # Fallback template if no API key
        return _fallback_email(domain, industry, buyer_types, company_name)

    company_line = f"I noticed {company_name} is building in the {industry} space." if company_name else f"I came across your work in the {industry} space."

    prompt = f"""Write a short, natural cold outreach email to sell the domain {domain}.

Context:
- Domain: {domain}
- Industry: {industry}
- Target buyers: {buyer_types}
- Specific company (if known): {company_name or 'not specified'}
- Estimated value: ${est_low:,}–${est_high:,}
- Sender name: {SENDER_NAME or '[Your Name]'}
- Sender email: {SENDER_EMAIL or '[Your Email]'}

Rules:
- Maximum 5 sentences total
- Sound like a human, not a sales robot
- Don't mention "domain flipping" or that you're a domain investor
- Don't include a price in the email — let them ask
- Subject line should be simple and curiosity-driven
- End with a soft call to action (reply if interested)
- DO NOT use phrases like "I hope this email finds you well"

Output format — return ONLY valid JSON, no other text:
{{
  "subject": "...",
  "body": "..."
}}"""

    try:
        async with aiohttp.ClientSession() as session:
            resp = await session.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-sonnet-4-20250514",
                    "max_tokens": 400,
                    "messages": [{"role": "user", "content": prompt}]
                },
                timeout=aiohttp.ClientTimeout(total=20)
            )
            if resp.status == 200:
                data = await resp.json()
                text = data["content"][0]["text"].strip()
                text = text.replace("```json","").replace("```","").strip()
                email_data = json.loads(text)
                return f"Subject: {email_data['subject']}\n\n{email_data['body']}"
    except Exception as e:
        log("OUTREACH", f"  AI email generation failed: {str(e)[:60]}")

    return _fallback_email(domain, industry, buyer_types, company_name)


def _fallback_email(domain: str, industry: str, buyer_types: str, company: str = "") -> str:
    to_line = f"Hi {company} team," if company else "Hi there,"
    return (
        f"Subject: {domain} — available\n\n"
        f"{to_line}\n\n"
        f"I own {domain} and thought it might be a good fit for a company working in {industry}.\n\n"
        f"It's currently available — happy to discuss if you're interested.\n\n"
        f"Best,\n{SENDER_NAME or '[Your Name]'}\n{SENDER_EMAIL or '[Your Email]'}"
    )


# ── MAIN BUYER MATCHER ────────────────────────────────────────────────────────
class BuyerMatcher:
    async def process(self, results: list[dict]) -> list[dict]:
        """
        For each domain result, find buyers + generate outreach email.
        Adds 'buyers' and 'outreach_email' keys to each result.
        """
        log("OUTREACH", f"Generating buyer matches for {len(results)} domains...")

        async with aiohttp.ClientSession() as session:
            for r in results:
                domain   = r["domain"]
                industry, buyers = get_vertical_context(domain)

                # Find funded companies
                companies = await find_funded_companies(session, industry, limit=3)
                r["buyers"] = companies

                # Generate outreach email
                top_company = companies[0]["name"] if companies else ""
                email = await generate_outreach_email(
                    domain      = domain,
                    industry    = industry,
                    buyer_types = buyers,
                    company_name= top_company,
                    est_low     = r.get("est_low", 0),
                    est_high    = r.get("est_high", 0),
                )
                r["outreach_email"] = email
                r["industry"]       = industry
                r["buyer_types"]    = buyers

                log("OUTREACH", f"  ✓ {domain} — {len(companies)} buyers found, email drafted")
                await asyncio.sleep(0.5)

        return results

    def export_emails(self, results: list[dict], path: str = "outreach_emails.txt"):
        """Export all outreach emails to a text file"""
        lines = []
        for r in results:
            if not r.get("outreach_email"):
                continue
            lines.append("=" * 60)
            lines.append(f"DOMAIN: {r['domain']}  |  Score: {r.get('score')}  |  Est: ${r.get('est_low',0):,}–${r.get('est_high',0):,}")
            lines.append(f"Industry: {r.get('industry','')}")
            if r.get("buyers"):
                lines.append(f"Top buyers: {', '.join(b['name'] for b in r['buyers'][:3] if b['name'])}")
            lines.append("")
            lines.append(r["outreach_email"])
            lines.append("")

        with open(path, "w") as f:
            f.write("\n".join(lines))

        log("OUTREACH", f"Emails exported to {path}")
        return path
