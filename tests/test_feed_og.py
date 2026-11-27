"""The link picture: 1200x630, today's yields for all three in fixed order, dated, the same bytes for the
same feed, and yesterday's picture kept when anything fails. Offline: Sora stands in for the headline face."""
import io
import json
import pathlib
import re

import pytest

PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402

from datproof_feed import og, pages  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
FEED = pages.load(ROOT / "site" / "v1")
HOME = "https://lucascashwell3-ai.github.io/datproof/"


def fonts():
    return og.faces(display=og.SORA)


def test_picture_is_1200x630_png_and_says_todays_figures():
    png = og.render(FEED, fonts())
    og.check(png)
    assert Image.open(io.BytesIO(png)).size == (1200, 630)
    c = og.content(FEED)
    assert [r["t"] for r in c["rows"]] == ["STRC", "SATA", "SATS"]
    for r, i in zip(c["rows"], pages.lead(FEED)):
        assert r["y"] == pages.pct(pages.val(i["yield_pct"]))
    assert c["date"] == f"Yields at the {pages.day(pages.price_date(FEED))} close"
    assert c["range"] == pages.hl_range(FEED)


def test_same_feed_same_bytes():
    assert og.render(FEED, fonts()) == og.render(FEED, fonts())


def test_a_missing_yield_stops_the_picture():
    feed = json.loads(json.dumps(FEED))
    feed["instruments"][1]["yield_pct"] = {"value": None, "reason": "nasdaq did not answer"}
    with pytest.raises(og.OgError, match="SATA has no yield today"):
        og.content(feed)


def test_a_failed_build_keeps_yesterdays_picture(tmp_path, monkeypatch):
    (tmp_path / "v1").mkdir()
    (tmp_path / "v1" / "instruments.json").write_text("{}")
    (tmp_path / "og.png").write_bytes(b"yesterday")
    monkeypatch.setattr(og, "CACHE", tmp_path / "no-fonts")
    assert og.main(["--site", str(tmp_path)]) == 1
    assert (tmp_path / "og.png").read_bytes() == b"yesterday"


def test_without_the_headline_face_nothing_is_written(tmp_path):
    with pytest.raises(og.OgError, match="font missing"):
        og.faces(cache=tmp_path)


def test_check_refuses_a_wrong_size():
    buf = io.BytesIO()
    Image.new("RGB", (1200, 600)).save(buf, format="PNG")
    with pytest.raises(og.OgError):
        og.check(buf.getvalue())


def test_page_tags_point_at_the_picture_with_absolute_urls():
    head = (ROOT / "site" / "index.html").read_text().split("</head>")[0]
    assert f'<meta property="og:image" content="{HOME}og.png">' in head
    assert '<meta property="og:image:width" content="1200">' in head
    assert '<meta property="og:image:height" content="630">' in head
    assert re.search(r'<meta property="og:image:alt" content="[^"]{20,}">', head)
    assert '<meta name="twitter:card" content="summary_large_image">' in head
    assert f'<meta name="twitter:image" content="{HOME}og.png">' in head
    assert (ROOT / "site" / "og.png").exists()


def test_daily_job_builds_the_picture_and_a_failure_turns_the_run_red():
    wf = (ROOT / ".github" / "workflows" / "grid.yml").read_text()
    assert "python -m datproof_feed.og --fetch-fonts $flag" in wf
    assert "og_code: ${{ steps.og.outputs.og_code }}" in wf
    assert 'if [ "$og" != "0" ]; then' in wf
    assert " site/og.png" in next(ln for ln in wf.splitlines() if ln.strip().startswith("git add "))
    assert " pillow " in wf


def test_headline_face_is_never_committed():
    tracked = [p.name for p in (ROOT / "assets" / "fonts").iterdir()]
    assert not any("Gambetta" in n for n in tracked)
    assert ".cache/" in (ROOT / ".gitignore").read_text()
