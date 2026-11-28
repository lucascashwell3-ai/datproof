"""The home page is the product page: one address everywhere, /next/ sends readers home, the grid
page lives at /grid/, and the daily job writes the home page and never the old paths."""
import json
import pathlib
import re

from datproof_feed import pages

ROOT = pathlib.Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
HOME = "https://datproof.com/"


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_home_page_is_the_product_page_with_one_address():
    page = read("site/index.html")
    assert f'<link rel="canonical" href="{HOME}">' in page
    assert f'<meta property="og:url" content="{HOME}">' in page
    assert "<!--feed:panels-->" in page and "Earn <span" in page
    assert 'src="next/app.js' in page and 'href="next/styles.css' in page
    assert 'href="favicon.svg"' in page and "../" not in re.sub(r"https?://\S+", "", page.split("<main>")[0])


def test_page_script_reads_the_feed_beside_the_home_page():
    js = read("site/next/app.js")
    assert 'load("v1/")' in js and 'load("next/v1-sample/")' in js
    assert '"../v1/"' not in js


def test_old_next_address_sends_readers_home_keeping_the_section():
    stub = read("site/next/index.html")
    assert f'<link rel="canonical" href="{HOME}">' in stub
    assert 'location.replace("../" + location.search + location.hash)' in stub
    assert '<noscript><meta http-equiv="refresh" content="0; url=../"></noscript>' in stub
    assert f'href="{HOME}"' in stub
    assert "<!--feed:" not in stub and len(stub) < 2000
    assert f"{HOME}index.md" in read("site/next/index.md")


def test_every_description_names_the_home_address_never_next():
    for rel in ("site/index.md", "site/llms.txt", "README.md", "datproof_feed/server.py",
                "skills/park-idle-cash/SKILL.md", "datproof_feed/pages.py"):
        text = read(rel)
        assert HOME in text or 'HOME = BASE + "/"' in text, rel
        assert "datproof/next" not in text and "{BASE}/next" not in text, rel


def test_sitemap_lists_the_home_page_twin_llms_and_feed():
    legal = [HOME + p + t for p in ("privacy/", "terms/") for t in ("", "index.md")]
    want = [HOME, HOME + "index.md", HOME + "llms.txt", HOME + "v1/instruments.json"] + legal
    assert re.findall(r"<loc>([^<]+)</loc>", read("site/sitemap.xml")) == want
    xml = pages.sitemap({"date": "2026-11-20"})
    assert re.findall(r"<loc>([^<]+)</loc>", xml) == want
    assert xml.count("<lastmod>2026-11-20</lastmod>") == 4  # the privacy and terms pages carry their own date
    assert xml.count(f"<lastmod>{pages.LEGAL_UPDATED}</lastmod>") == 4


def test_grid_page_lives_at_grid_and_links_home():
    builder = read("scripts/build_grid_site.py")
    assert 'OUT = ROOT / "site" / "grid" / "index.html"' in builder
    assert 'TEMPLATE = ROOT / "site" / "grid" / "template.html"' in builder
    for rel in ("site/grid/template.html", "site/grid/index.html"):
        page = read(rel)
        assert '<a href="../">DATproof home</a>' in page
        assert 'href="../favicon.svg"' in page and '<script src="coverage.js"></script>' in page
    assert (SITE / "grid" / "coverage.js").exists()
    assert not (SITE / "template.html").exists() and not (SITE / "coverage.js").exists()
    assert "url=../grid/#stress" in read("site/story/index.html")


def test_daily_job_commits_the_home_page_and_never_the_old_paths():
    wf = read(".github/workflows/grid.yml")
    add = next(line for line in wf.splitlines() if line.strip().startswith("git add "))
    for path in ("site/index.html", "site/index.md", "site/llms.txt", "site/sitemap.xml", "site/v1"):
        assert f" {path}" in add, path
    assert "site/next" not in add
    assert "site/grid" not in add  # /grid/ is frozen: published as last built, never rebuilt


# ---------- visitor counter hook and feedback link ----------

FEEDBACK = "https://github.com/lucascashwell3-ai/datproof/issues/new?template=feedback.md"


def test_counter_is_off_when_empty_and_the_page_matches_the_config():
    off = {"counter": {"provider": "", "code": ""}}
    assert pages.counter_tag(off) == "" and pages.counter_tag({}) == "" and pages.counter_tag(None) == ""
    cfg = json.loads(read("site/config.json"))
    tag = pages.counter_tag(cfg)  # the committed setting, on or off, must be valid
    page = read("site/index.html")
    assert f"<!--feed:counter-->{tag}<!--/feed:counter-->" in page
    if not tag:
        assert "goatcounter" not in page and "cloudflareinsights" not in page


def test_counter_switches_on_with_one_value():
    tag = pages.counter_tag({"counter": {"provider": "goatcounter", "code": "datproof"}})
    assert tag == '<script data-goatcounter="https://datproof.goatcounter.com/count" async src="https://gc.zgo.at/count.js"></script>'
    tag = pages.counter_tag({"counter": {"provider": "cloudflare", "code": "0123456789abcdef0123456789abcdef"}})
    assert 'data-cf-beacon=\'{"token": "0123456789abcdef0123456789abcdef"}\'' in tag
    feed = pages.load(SITE / "v1")
    out = pages.render(feed, read("site/index.html"), {"counter": {"provider": "goatcounter", "code": "datproof"}})
    assert out["index.html"].count("gc.zgo.at/count.js") == 1
    assert "gc.zgo.at" not in out["index.md"] and "gc.zgo.at" not in out["llms.txt"]


def test_the_live_counter_is_one_cookie_free_script_and_leaves_when_emptied():
    cfg = json.loads(read("site/config.json"))
    assert cfg["counter"] == {"provider": "goatcounter", "code": "lucascashwell"}
    want = ('<script data-goatcounter="https://lucascashwell.goatcounter.com/count" async '
            'src="https://gc.zgo.at/count.js"></script>')
    page = read("site/index.html")
    assert page.count("<script data-goatcounter=") == 1 and page.count(want) == 1
    for rel in ("site/index.md", "site/llms.txt", "site/grid/index.html", "site/next/index.html"):
        if (ROOT / rel).exists():
            assert "goatcounter" not in read(rel) and "gc.zgo.at" not in read(rel), rel
    assert "cookie" not in pages.counter_tag(cfg).lower()
    assert "document.cookie" not in page and "document.cookie" not in read("site/next/app.js")
    # built once with the counter, then rebuilt with the provider emptied: the script is gone
    feed = pages.load(SITE / "v1")
    on = pages.render(feed, page, cfg)["index.html"]
    assert on.count(want) == 1
    off = pages.render(feed, on, {"counter": {"provider": "", "code": ""}})["index.html"]
    assert "goatcounter" not in off and "gc.zgo.at" not in off
    assert "<!--feed:counter--><!--/feed:counter-->" in off


def test_a_bad_counter_value_is_refused_not_printed():
    import pytest
    for bad in ({"provider": "googleanalytics", "code": "G-123"},
                {"provider": "goatcounter", "code": 'x"><script>alert(1)</script>'},
                {"provider": "cloudflare", "code": "not-a-token"}):
        with pytest.raises(pages.PageError, match="config.json"):
            pages.counter_tag({"counter": bad})


def test_feedback_line_at_the_foot_with_a_template_and_no_contact_details():
    page = read("site/index.html")
    foot = page[page.index('<footer class="wrap foot">'):page.index("</footer>")]
    assert f'Something missing or wrong? <a href="{FEEDBACK}" rel="noopener">Tell us</a>' in foot
    assert f"Something missing or wrong? Tell us: {FEEDBACK}" in read("site/index.md")
    tpl = read(".github/ISSUE_TEMPLATE/feedback.md")
    assert "What were you trying to find out?" in tpl and "What was missing or wrong?" in tpl
    assert "@" not in tpl and "mailto" not in tpl
