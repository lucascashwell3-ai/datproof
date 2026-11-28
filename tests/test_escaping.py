"""Outside text written into pages comes out inert.

Names, notes and links come from fund feeds, filings and broker lists. A `</script><script>` in any of
them must not run in a visitor's browser, and a `javascript:` link must never become an href."""
from __future__ import annotations

import copy
import json
import pathlib
import re
import sys

import pytest

from datproof_feed import pages

ROOT = pathlib.Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
sys.path.insert(0, str(ROOT / "scripts"))
import build_grid_site as grid  # noqa: E402

PLANT = '</script><script>alert(1)</script><!-- "x"  '


def _scripts(html_text: str) -> list[str]:
    return re.findall(r"<script[^>]*>(.*?)</script>", html_text, flags=re.S)


# ---------- grid page (/grid/): data embedded in a <script> block ----------

def test_script_json_is_inert_and_round_trips():
    out = grid.script_json({"name": PLANT, "n": [1, 2]})
    assert "<" not in out and " " not in out
    assert json.loads(out) == {"name": PLANT, "n": [1, 2]}


def test_planted_name_from_outside_feed_cannot_end_the_grid_script(tmp_path, monkeypatch):
    companies = copy.deepcopy(grid.COMPANIES)
    companies[0]["name"] = PLANT
    monkeypatch.setattr(grid, "COMPANIES", companies)
    monkeypatch.setattr(grid, "OUT", tmp_path / "index.html")
    grid.main()
    page = (tmp_path / "index.html").read_text()
    data = next(s for s in _scripts(page) if "window.DATA=" in s)
    assert "alert(1)" in data, "the planted name should be in the data, as data"
    assert "</script" not in data.lower() and "<!--" not in data and "<script" not in data.lower()
    assert page.count("alert(1)") == 1, "the planted text appears once, inside the data block only"


def test_old_raw_dump_would_have_failed():
    raw = "window.DATA=" + json.dumps({"name": PLANT}) + ";"
    assert "</script>" in raw  # what the builder wrote before: this ended the block early


def test_grid_template_links_only_web_addresses():
    t = (SITE / "grid" / "template.html").read_text()
    assert "const web=u=>" in t
    assert 'href="${url}"' not in t, "a source address must not go into href unchecked"
    assert "const link=(url,text)=>web(url)?" in t


# ---------- home page: hrefs and the FAQ block ----------

@pytest.mark.parametrize("bad", ["javascript:alert(1)", "data:text/html,<script>alert(1)</script>",
                                 'https://x.com/" onmouseover="alert(1)', " https://x.com", None, 5])
def test_url_refuses_anything_but_a_web_address(bad):
    with pytest.raises(pages.PageError):
        pages.url(bad)


def test_url_passes_and_escapes_a_web_address():
    assert pages.url("https://www.sec.gov/a?b=1&c=2") == "https://www.sec.gov/a?b=1&amp;c=2"


def test_linkify_escapes_text_and_checks_links():
    out = pages.linkify(f"{PLANT} (2026-11-27, https://www.sec.gov/x)")
    assert "<script" not in out and "&lt;/script&gt;" in out
    assert '<a href="https://www.sec.gov/x"' in out


def test_faq_block_cannot_be_ended_by_its_text(monkeypatch):
    monkeypatch.setattr(pages, "faq", lambda feed: [(PLANT, PLANT)])
    ld = pages.faq_ld({"date": "2026-11-27"})
    body = ld[len('<script type="application/ld+json">'):-len("</script>")]
    assert "<" not in body
    assert json.loads(body)["mainEntity"][0]["name"] == PLANT


def _live():
    return pages.load(SITE / "v1"), (SITE / "index.html").read_text()


def test_planted_broker_link_stops_the_page_build():
    feed, tpl = _live()
    if not pages.buy_doc(feed).get("brokers"):
        pytest.skip("no brokers in today's feed")
    bad = copy.deepcopy(feed)
    b = pages.buy_doc(bad)["brokers"][0]
    t = next(t for t, c in (b.get("tickers") or {}).items() if (c or {}).get("url"))
    b["tickers"][t]["url"] = "javascript:alert(1)"
    with pytest.raises(pages.PageError, match="not a web address"):
        pages.render(bad, tpl)


def test_planted_broker_name_comes_out_escaped():
    feed, tpl = _live()
    if not pages.buy_doc(feed).get("brokers"):
        pytest.skip("no brokers in today's feed")
    bad = copy.deepcopy(feed)
    pages.buy_doc(bad)["brokers"][0]["name"] = PLANT
    out = pages.render(bad, tpl)["index.html"]
    assert "<script>alert(1)" not in out
    assert "&lt;/script&gt;&lt;script&gt;alert(1)" in out


def test_planted_feed_date_stops_the_page_build(tmp_path):
    v1 = tmp_path / "v1"
    v1.mkdir()
    feed = json.loads((SITE / "v1" / "instruments.json").read_text())
    feed["date"] = "2026-11-27</lastmod><x>"
    (v1 / "instruments.json").write_text(json.dumps(feed))
    with pytest.raises(pages.PageError, match="feed date"):
        pages.load(v1)
