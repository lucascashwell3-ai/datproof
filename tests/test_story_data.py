"""The story band left the front page in Sep 2026: its page and chart data are kept, unchanged,
in archive/story-2026-09/, and /story now sends readers to the stress test (#stress)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "archive" / "story-2026-09"


def test_archived_story_data_kept():
    data = ARCHIVE / "story-data.js"
    assert data.exists()
    assert data.read_text(encoding="utf-8").startswith("window.STORY_DATA = ")


def test_archived_story_page_still_references_its_data():
    page = (ARCHIVE / "index.html").read_text(encoding="utf-8")
    assert '<script src="story-data.js"></script>' in page


def test_story_url_redirects_to_the_stress_test():
    page = (ROOT / "site" / "story" / "index.html").read_text(encoding="utf-8")
    assert 'http-equiv="refresh" content="0; url=../#stress"' in page
    assert 'href="../#stress"' in page
    assert not (ROOT / "site" / "story" / "story-data.js").exists()


def test_front_page_no_longer_loads_the_story_engine():
    template = (ROOT / "site" / "template.html").read_text(encoding="utf-8")
    for gone in ("story/story-data.js", "__storySpine", 'id="story"', "stageNav", 'href="#story"'):
        assert gone not in template, gone
