"""Two statements the pages must carry: the Sharpe line is past prices, not a forecast; /grid/ says what DATproof is not."""
from __future__ import annotations

import pathlib
import re

from datproof_feed import pages

ROOT = pathlib.Path(__file__).resolve().parents[1]
STATEMENT = "It is free. It holds no money, places no orders and is not advice."


def test_sharpe_line_says_past_prices_not_a_forecast():
    feed = pages.load(ROOT / "site" / "v1")
    line = pages.sharpe_line(feed)
    assert line.startswith("Over the past year") and line.endswith("Past prices, not a forecast.")
    page = (ROOT / "site" / "index.html").read_text()
    lift = re.search(r'<p class="fine lift-sharpe">(.*?)</p>', page, re.S).group(1)
    assert "Past prices, not a forecast." in lift


def test_grid_page_carries_the_home_page_statement():
    assert STATEMENT in pages.ABOUT and STATEMENT in pages.ABOUT_MD
    for f in ("template.html", "index.html"):
        foot = (ROOT / "site" / "grid" / f).read_text().split('<footer id="foot">', 1)[1].split("</footer>", 1)[0]
        assert STATEMENT in foot, f
        assert 'id="foot-data"' in foot, "the build line goes in its own span so the statement stays"
