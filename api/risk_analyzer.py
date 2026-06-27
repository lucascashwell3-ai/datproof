"""
risk_analyzer.py

Sends wallet transaction data to Claude API and gets back a structured
risk assessment mapped to FATF, BSA, OFAC, and COSO frameworks.

Returns a RiskReport dataclass ready to be rendered into a PDF.
"""

import os
import json
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Optional
import anthropic
from dotenv import load_dotenv
from api.blockchain_fetcher import WalletProfile, Transaction

load_dotenv()

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


# ── Data Models ──────────────────────────────────────────────────────────────

@dataclass
class RiskFinding:
    finding_id: str          # e.g. "F-001"
    title: str
    description: str
    risk_rating: str         # "Critical" | "High" | "Medium" | "Low" | "Informational"
    framework: str           # "FATF" | "BSA" | "OFAC" | "COSO"
    framework_ref: str       # e.g. "FATF Recommendation 16 (Travel Rule)"
    recommendation: str
    evidence: str            # Specific tx hashes or patterns observed


@dataclass
class RiskReport:
    wallet_address: str
    chain: str
    generated_at: str
    analyst_note: str        # Executive summary from Claude
    overall_risk_rating: str # "Critical" | "High" | "Medium" | "Low"
    risk_score: int          # 0–100
    tx_count_analyzed: int
    total_volume_native: float
    unique_counterparties: int
    findings: list[RiskFinding] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)   # Quick-reference red flags
    error: Optional[str] = None


# ── Prompt Builder ───────────────────────────────────────────────────────────

def _build_transaction_summary(profile: WalletProfile) -> str:
    """Condense wallet data into a compact string for the prompt."""
    lines = [
        f"Wallet Address: {profile.address}",
        f"Chain: {profile.chain}",
        f"Total Transactions Analyzed: {profile.tx_count}",
        f"Total Received: {profile.total_received:.6f} {profile.chain}",
        f"Total Sent: {profile.total_sent:.6f} {profile.chain}",
        f"Unique Counterparties: {profile.unique_counterparties}",
        "",
        "Recent Transactions (most recent first):",
    ]

    for i, tx in enumerate(profile.transactions[:25]):  # Cap at 25 for token efficiency
        ts = datetime.fromtimestamp(tx.timestamp, tz=timezone.utc).strftime("%Y-%m-%d") if tx.timestamp else "unknown"
        lines.append(
            f"  [{i+1}] {ts} | {tx.value_native:.6f} {tx.chain} | "
            f"from={tx.from_address[:10]}... to={tx.to_address[:10]}... | "
            f"block={tx.block} | error={tx.is_error}"
        )

    return "\n".join(lines)


def _build_prompt(profile: WalletProfile) -> str:
    tx_summary = _build_transaction_summary(profile)

    return f"""You are a senior blockchain compliance analyst and IT auditor.
Your task is to analyze the following blockchain wallet transaction data and produce a structured risk assessment report.

Apply the following compliance frameworks in your analysis:
- FATF (Financial Action Task Force) — travel rule compliance, layering/placement/integration detection, suspicious patterns
- BSA (Bank Secrecy Act) — suspicious activity indicators, structuring, unusual transaction patterns
- OFAC (Office of Foreign Assets Control) — sanctions exposure, high-risk jurisdiction patterns
- COSO (Committee of Sponsoring Organizations) — internal control framework, risk and control environment assessment

WALLET DATA:
{tx_summary}

Produce your response as a single valid JSON object with this exact structure:
{{
  "overall_risk_rating": "High",
  "risk_score": 72,
  "analyst_note": "2-3 sentence executive summary suitable for a compliance officer",
  "flags": [
    "High transaction velocity relative to counterparty diversity",
    "Potential structuring pattern detected in 3 transactions"
  ],
  "findings": [
    {{
      "finding_id": "F-001",
      "title": "Short, specific finding title",
      "description": "Detailed description of what was observed and why it is a risk",
      "risk_rating": "High",
      "framework": "FATF",
      "framework_ref": "FATF Recommendation 16 (Travel Rule)",
      "recommendation": "Specific, actionable remediation step",
      "evidence": "Specific transaction hashes or patterns from the data above"
    }}
  ]
}}

Rules:
- overall_risk_rating must be one of: Critical, High, Medium, Low
- risk_score is an integer 0-100 (100 = highest risk)
- Each finding's risk_rating must be one of: Critical, High, Medium, Low, Informational
- Each finding's framework must be one of: FATF, BSA, OFAC, COSO
- Produce between 2 and 6 findings depending on what the data actually supports
- Base all findings on the actual transaction data provided — do not fabricate patterns not present in the data
- If the wallet appears low risk, say so clearly and produce informational findings only
- Return ONLY the JSON object, no markdown, no explanation outside the JSON
"""


# ── Main Analyzer ────────────────────────────────────────────────────────────

def analyze_wallet(profile: WalletProfile) -> RiskReport:
    """
    Send wallet data to Claude and parse the structured risk report response.
    """
    if profile.error:
        return RiskReport(
            wallet_address=profile.address,
            chain=profile.chain,
            generated_at=datetime.now(timezone.utc).isoformat(),
            analyst_note="",
            overall_risk_rating="Unknown",
            risk_score=0,
            tx_count_analyzed=0,
            total_volume_native=0,
            unique_counterparties=0,
            error=f"Data fetch error: {profile.error}",
        )

    prompt = _build_prompt(profile)

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",  # Fast + cheap — ideal for report generation
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text.strip()

    # Strip markdown code fences if Claude wraps in them
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    data = json.loads(raw)

    findings = [
        RiskFinding(
            finding_id=f.get("finding_id", f"F-{i+1:03d}"),
            title=f.get("title", ""),
            description=f.get("description", ""),
            risk_rating=f.get("risk_rating", "Informational"),
            framework=f.get("framework", ""),
            framework_ref=f.get("framework_ref", ""),
            recommendation=f.get("recommendation", ""),
            evidence=f.get("evidence", ""),
        )
        for i, f in enumerate(data.get("findings", []))
    ]

    return RiskReport(
        wallet_address=profile.address,
        chain=profile.chain,
        generated_at=datetime.now(timezone.utc).isoformat(),
        analyst_note=data.get("analyst_note", ""),
        overall_risk_rating=data.get("overall_risk_rating", "Unknown"),
        risk_score=int(data.get("risk_score", 0)),
        tx_count_analyzed=profile.tx_count,
        total_volume_native=profile.total_received + profile.total_sent,
        unique_counterparties=profile.unique_counterparties,
        findings=findings,
        flags=data.get("flags", []),
    )
