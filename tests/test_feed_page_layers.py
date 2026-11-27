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
