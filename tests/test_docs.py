"""Public docs keep a plain, reader-friendly register.

Public-facing copy (README, landing, tearsheet) avoids dense finance/accounting
acronyms and jargon so it reads clearly to a general audience. The analytical
rigor still lives in the engine (risk.py assertions + frameworks); this test just
guards the public copy's vocabulary, same as the landing page and tearsheet.
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
