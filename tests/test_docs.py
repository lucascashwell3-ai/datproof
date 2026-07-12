"""Public-surface docs stay jargon-light.

Per the 2026-07-10 repositioning spec, public-facing surfaces use an educational
register — no audit-framework / consultant branding (COSO, SOX, FASB ASU 2023-08,
"audit assertion", ICFR, "IT auditor"). The rigor still lives in the engine
(risk.py assertions + frameworks); it just isn't advertised on public copy.
This mirrors the vocabulary bans enforced on the landing page and tearsheet.
"""

from pathlib import Path

README = Path(__file__).resolve().parents[1] / "README.md"

BANNED = (
    "COSO", "SOX", "ASU 2023-08", "FASB", "ICFR",
    "audit assertion", "audit-assertion", "audit-grade",
    "IT auditor", "audit language", "audit practices",
)


def test_readme_is_de_audited():
    text = README.read_text(encoding="utf-8")
    for banned in BANNED:
        assert banned not in text, f"banned framing in README.md: {banned}"
