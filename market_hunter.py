"""generators/ai_generator.py — Uses Claude API to generate brandable .ai domain ideas"""
import os
import json
import aiohttp

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

SYSTEM_PROMPT = """You are a domain name investment expert specializing in .ai domains.
Your job is to generate highly brandable, valuable .ai domain names that could be flipped for profit.

Focus on:
- Short, memorable names (4-12 chars before .ai)
- Industry verticals: healthcare, legal, finance, education
- Action words + industry terms
- Names that Fortune 500 companies or funded startups would pay $10K-$500K for
- Emerging AI use cases that aren't yet saturated

Return ONLY a JSON array of domain names (strings), no explanation.
Example: ["triage.ai", "audit.ai", "careplan.ai"]"""


class AIGenerator:
    async def generate(self, limit: int = 100) -> list[str]:
        if not ANTHROPIC_API_KEY:
            return []

        prompts = [
            "Generate 25 high-value .ai domains for healthcare and medical AI startups. Focus on clinical workflows, diagnostics, and billing automation.",
            "Generate 25 high-value .ai domains for legal tech AI companies. Think contract management, discovery, compliance, immigration.",
            "Generate 25 high-value .ai domains for fintech and financial AI. Think risk, fraud, credit, wealth management, compliance.",
            "Generate 25 high-value .ai domains for education AI. Think tutoring, assessment, professional certification, corporate training.",
        ]

        all_domains = set()

        async with aiohttp.ClientSession() as session:
            for prompt in prompts:
                try:
                    payload = {
                        "model": "claude-sonnet-4-20250514",
                        "max_tokens": 500,
                        "system": SYSTEM_PROMPT,
                        "messages": [{"role": "user", "content": prompt}]
                    }
                    headers = {
                        "x-api-key": ANTHROPIC_API_KEY,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json"
                    }
                    async with session.post(
                        "https://api.anthropic.com/v1/messages",
                        json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=20)
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            text = data["content"][0]["text"].strip()
                            # Strip markdown fences if present
                            text = text.replace("```json","").replace("```","").strip()
                            domains = json.loads(text)
                            for d in domains:
                                d = d.strip().lower()
                                if not d.endswith(".ai"):
                                    d = d + ".ai"
                                all_domains.add(d)
                except Exception as e:
                    print(f"[AI GEN] Error on prompt batch: {e}")
                    continue

        return list(all_domains)[:limit]
