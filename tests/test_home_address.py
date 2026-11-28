"""One home address: https://datproof.com/. The old project address must not come back in any
published file, the README, the skill, or the code that writes the pages and serves the feed."""
import pathlib

from datproof_feed import pages, server

ROOT = pathlib.Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
HOME = "https://datproof.com/"
OLD = "lucascashwell3-ai.github.io/datproof"
TEXT = {".html", ".md", ".txt", ".xml", ".json", ".js", ".css", ".svg"}


def checked_files():
    for path in sorted(SITE.rglob("*")):
        if path.is_file() and path.suffix in TEXT:
            yield path
    for rel in ("README.md", "skills/park-idle-cash/SKILL.md", "datproof_feed/pages.py",
                "datproof_feed/server.py", ".github/workflows/grid.yml"):
        yield ROOT / rel


def test_old_address_appears_nowhere_published():
    hits = [str(p.relative_to(ROOT)) for p in checked_files() if OLD in p.read_text(encoding="utf-8")]
    assert hits == [], hits


def test_code_names_the_home_address():
    assert pages.HOME == HOME
    assert server.HOME == HOME
    assert server.DEFAULT_FEED == HOME + "v1"


def test_robots_allows_all_and_points_at_the_sitemap():
    robots = (SITE / "robots.txt").read_text(encoding="utf-8")
    assert "User-agent: *" in robots and "Allow: /" in robots and "Disallow" not in robots
    assert f"Sitemap: {HOME}sitemap.xml" in robots.splitlines()
