"""The story chart data lives in one file, not duplicated between the standalone
/story page and the front page's native story section.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STORY_DATA = ROOT / "site" / "story" / "story-data.js"


def test_story_data_file_exists():
    assert STORY_DATA.exists()
    text = STORY_DATA.read_text(encoding="utf-8")
    assert text.startswith("window.STORY_DATA = ")


def test_template_references_story_data():
    template = (ROOT / "site" / "template.html").read_text(encoding="utf-8")
    assert '<script src="story/story-data.js"></script>' in template


def test_story_page_references_story_data():
    story_page = (ROOT / "site" / "story" / "index.html").read_text(encoding="utf-8")
    assert '<script src="story-data.js"></script>' in story_page
