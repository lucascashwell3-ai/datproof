"""The "Liquid and steady" price charts draw the dashed $100 line, its "$100" label, the $95-$105 band
and the "within $5 of $100" sentence only for issues whose issuer states it aims to keep the price near $100."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "site" / "next" / "app.js").read_text()


def fn(name):
    m = re.search(r"^  function " + name + r"\(.*?^  }\n", APP, re.S | re.M)
    assert m, name
    return m.group(0)


def run(expr):
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    script = fn("priceGuides") + fn("paidLabel") + "function Y(p){return 300-p;}console.log(JSON.stringify(" + expr + "));"
    return json.loads(subprocess.run([node, "-e", script], capture_output=True, text=True, check=True).stdout)


def classes(marks):
    return [m[1]["class"] for m in marks]


def ticks(marks):
    return [m[2] for m in marks if m[1]["class"] == "c-tick"]


def test_no_dashed_line_or_label_without_the_aim():
    marks = run("priceGuides(false, 80, 105, 44, 300, Y)")
    assert "c-par" not in classes(marks) and "c-par-t" not in classes(marks)
    assert "c-band" not in classes(marks)
    # $100 is an ordinary gridline with an ordinary label, so the axis has no hole
    assert ticks(marks) == ["$80", "$90", "$100"]
    assert classes(marks).count("c-grid") == 3


def test_dashed_line_label_and_band_with_the_aim():
    marks = run("priceGuides(true, 70, 105, 44, 300, Y)")
    cs = classes(marks)
    assert cs.count("c-par") == 1 and cs.count("c-par-t") == 1 and cs.count("c-band") == 1
    assert [m[2] for m in marks if m[1]["class"] == "c-par-t"] == ["$100"]
    assert ticks(marks) == ["$70", "$80", "$90"]  # the dashed line stands in for the $100 gridline


def test_description_names_100_only_with_the_aim():
    assert "$100" not in run('paidLabel("SATS", false, 28, "$88.50")')
    assert "Within $5 of $100 on 82% of days." in run('paidLabel("STRC", true, 82, "$98.04")')


def test_chart_draws_through_the_guides():
    body = APP[APP.index("function drawPaid"):APP.index("// ---------- 3b.")]
    assert "issuer_aims_price_near_100" in body and "priceGuides(aims" in body and "paidLabel(" in body
    assert "c-par" not in body and "Within $5" not in body


def test_section_text_ties_no_issue_without_the_aim_to_100():
    html = (ROOT / "site" / "index.html").read_text()
    src = html[html.index("<!--feed:liquidsrc-->"):html.index("<!--/feed:liquidsrc-->")]
    assert "SATS" not in src
    md = (ROOT / "site" / "index.md").read_text()
    sec = md[md.index("## Liquid and steady"):md.index("## Bought under $100")]
    assert all("SATS" not in line for line in sec.splitlines() if "$100" in line)
