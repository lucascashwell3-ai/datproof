"""Every section of /next/: one heading, at most one line under it, the content, at most one source line."""
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
PAGE = (ROOT / "site" / "next" / "index.html").read_text()


def layers(page: str) -> dict[str, tuple[int, int, int]]:
    out = {}
    for m in re.finditer(r'<section class="wrap (?:block|hero)" id="(\w+)".*?</section>', page, re.S):
        body = m.group(0)
        out[m.group(1)] = (len(re.findall(r"<h2\b", body)), len(re.findall(r'class="sub"', body)),
                           len(re.findall(r'class="fine[ "]', body)))
    return out


def too_many(page: str) -> list[str]:
    return [f"{sid}: {h} headings, {s} lines under, {f} source lines" for sid, (h, s, f) in layers(page).items()
            if h > 1 or s > 1 or f > 1]


def test_each_section_has_one_heading_one_line_one_source_line():
    assert len(layers(PAGE)) >= 10
    assert too_many(PAGE) == []


def test_the_layer_check_catches_a_planted_second_line():
    planted = PAGE.replace('<h2 id="h-risk">What can go wrong</h2>',
                           '<h2 id="h-risk">What can go wrong</h2><p class="fine">one</p><p class="fine">two</p>')
    assert any(s.startswith("risk:") for s in too_many(planted))


MAX_SOURCE_LINE = 460  # characters: a short line, not a paragraph


def long_lines(page: str) -> list[str]:
    import html as h
    out = []
    for m in re.finditer(r'<p class="fine[^"]*"[^>]*>(.*?)</p>', page, re.S):
        text = h.unescape(re.sub(r"<[^>]+>", "", m.group(1)))
        if len(text) > MAX_SOURCE_LINE:
            out.append(text[:60])
    return out


def test_source_lines_are_short():
    assert long_lines(PAGE) == []


def test_the_length_check_catches_a_planted_paragraph():
    planted = PAGE.replace('<h2 id="h-risk">What can go wrong</h2>',
                           '<h2 id="h-risk">What can go wrong</h2><p class="fine">' + "word " * 100 + "</p>")
    assert long_lines(planted)


def headline_problems(page: str, md: str, rng: str) -> list[str]:
    import html as h
    from datproof_feed import pages
    want = pages.HEADLINE.format(range=rng)
    m = re.search(r'<h1[^>]*>(.*?)</h1>', page, re.S)
    got = h.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip() if m else ""
    out = [] if got == want else [f"page h1 is {got!r}, not {want!r}"]
    if not md.startswith(f"# DATproof: earn {rng} on your idle cash\n"):
        out.append("the twin's first heading does not match")
    if "agent's idle cash" in page or "agent's idle cash" in md:
        out.append("old agent-only headline found")
    return out


def test_the_headline_is_for_anyone_with_idle_cash():
    import json
    from datproof_feed import pages
    feed = json.loads((ROOT / "site" / "v1" / "instruments.json").read_text())
    md = (ROOT / "site" / "next" / "index.md").read_text()
    assert headline_problems(PAGE, md, pages.hl_range(feed)) == []
    assert pages.HEADLINE == "Earn {range} on your idle cash."


def test_the_headline_check_catches_the_old_wording():
    planted = PAGE.replace("on your idle cash.</h1>", "on your agent's idle cash.</h1>")
    md = (ROOT / "site" / "next" / "index.md").read_text()
    assert headline_problems(planted, md, "12–17%")
