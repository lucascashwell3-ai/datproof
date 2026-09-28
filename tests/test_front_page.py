"""Front page sections: credit family, stress test, and the next-up teaser. The page's own
coverage math (site/coverage.js) must reproduce each company's published figure at its price."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = (ROOT / "site" / "template.html").read_text(encoding="utf-8")
CREDIT = json.loads((ROOT / "data" / "credit.json").read_text())


def test_sections_in_contract_order():
    ids = ['id="grid"', 'id="credit"', 'id="stress"', 'id="why"', 'id="next"', 'class="act close"']
    positions = [TEMPLATE.index(i) for i in ids]
    assert positions == sorted(positions)


def test_nav_order():
    nav = re.search(r'<div class="links">(.*?)</div>', TEMPLATE).group(1)
    assert re.findall(r'href="([^"]+)"', nav)[:4] == ["#grid", "#credit", "#stress", "#why"]
    assert ">stress test</a>" in nav


def test_each_new_section_has_a_heading():
    for sid in ("credit", "stress", "next"):
        block = TEMPLATE[TEMPLATE.index(f'id="{sid}"'):]
        block = block[:block.index("</section>")]
        assert "<h2" in block, sid


def test_page_uses_shared_coverage_math():
    assert TEMPLATE.index('<script src="coverage.js"></script>') < TEMPLATE.index("<script>/*__DATA__*/</script>")
    assert "Cov=window.Coverage" in TEMPLATE
    assert "Cov.striveYears(" in TEMPLATE
    assert "Cov.strategyYears(" in TEMPLATE
    assert "* 100 *" not in TEMPLATE and "*100*" not in TEMPLATE  # no inline copy of the formula


def test_slider_is_labelled_and_announces_dollars():
    assert '<label for="btc-range">' in TEMPLATE
    assert 'type="range"' in TEMPLATE
    assert "setAttribute('aria-valuetext'" in TEMPLATE


def test_retired_pieces_and_banned_words_are_gone():
    assert ".beam" not in TEMPLATE
    low = TEMPLATE.lower()
    for word in ("ledger", "death spiral"):
        assert word not in low, word


def test_page_math_reproduces_strategy_published_figure():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    st = CREDIT["strategy"]
    script = (f"const C=require({json.dumps(str(ROOT / 'site' / 'coverage.js'))});"
              f"const s={json.dumps(st)};console.log(C.strategyYears(s,s.their_btc_price))")
    ours = float(subprocess.run([node, "-e", script], capture_output=True, text=True, check=True).stdout)
    assert round(ours, 1) == round(st["published_years"], 1)
