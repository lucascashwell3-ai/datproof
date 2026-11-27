"""The home page is the product page: one address everywhere, /next/ sends readers home, the grid
page lives at /grid/, and the daily job writes the home page and never the old paths."""
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
HOME = "https://lucascashwell3-ai.github.io/datproof/"


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
    xml = read("site/sitemap.xml")
    locs = re.findall(r"<loc>([^<]+)</loc>", xml)
    assert locs == [HOME, HOME + "index.md", HOME + "llms.txt", HOME + "v1/instruments.json"]
    date = json.loads(read("site/v1/instruments.json"))["date"]
    assert xml.count(f"<lastmod>{date}</lastmod>") == 4


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
    for path in ("site/index.html", "site/index.md", "site/llms.txt", "site/sitemap.xml", "site/grid/index.html", "site/v1"):
        assert f" {path}" in add, path
    assert "site/next" not in add
