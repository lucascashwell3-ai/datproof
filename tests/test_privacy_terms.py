"""The privacy and terms pages: both exist with Markdown twins, are linked from the foot of the home page and
/grid/, are in the sitemap, llms.txt and the home page's twin, carry no counter script, and the terms page says
it is not advice and carries the disclosure word for word. Each check is planted to fail once."""
from __future__ import annotations

import functools
import pathlib
import re

import pytest

from datproof_feed import pages

ROOT = pathlib.Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
HOME = pages.HOME
LEGAL = ("privacy", "terms")
COUNTER = re.compile(r"gc\.zgo\.at|data-goatcounter|goatcounter\.com/count|cloudflareinsights")
OVERCLAIM = re.compile(r"GDPR|CCPA|compl(y|iant|iance)|guarantee|secure|arbitration|governing law|jurisdiction|years of age",
                       re.I)


def foot(page: str) -> str:
    return page[page.index('<footer class="wrap foot">'):page.index("</footer>")]


def problems(files: dict[str, str]) -> list[str]:
    out = []
    for p in LEGAL:
        for twin in ("index.html", "index.md"):
            if f"{p}/{twin}" not in files:
                out.append(f"{p}/{twin} missing")
    home_foot = foot(files["index.html"])
    for p in LEGAL:
        if f'<a href="{p}/">' not in home_foot:
            out.append(f"home foot has no link to {p}/")
        for twin in ("", "index.md"):
            if f"<loc>{HOME}{p}/{twin}</loc>" not in files["sitemap.xml"]:
                out.append(f"sitemap lacks {p}/{twin}")
        for twin in ("", "index.md"):
            for rel in ("llms.txt", "index.md"):
                if not re.search(rf"{re.escape(HOME + p + '/' + twin)}(\s|\)|$)", files[rel]):
                    out.append(f"{rel} lacks {p}/{twin}")
    for rel in (f"{p}/index.html" for p in LEGAL):
        if rel in files and COUNTER.search(files[rel]):
            out.append(f"{rel} carries a counter script")
    for rel in ("terms/index.html", "terms/index.md"):
        text = files.get(rel, "")
        for must in (pages.NOT_ADVICE, pages.DISCLOSURE, "not investment, tax or legal advice"):
            if must not in text:
                out.append(f"{rel} lacks: {must}")
    for rel in (f"{p}/{t}" for p in LEGAL for t in ("index.html", "index.md")):
        m = OVERCLAIM.search(files.get(rel, ""))
        if m:
            out.append(f"{rel} claims '{m.group(0)}'")
    return out


@functools.lru_cache(maxsize=1)
def _rendered() -> tuple[tuple[str, str], ...]:
    config = pages.load_config(SITE)
    assert pages.counter_tag(config), "site/config.json names no counter, so the no-counter check would prove nothing"
    out = pages.render(pages.load(SITE / "v1"), (SITE / "index.html").read_text(), config)
    return tuple(out.items())


def rendered() -> dict[str, str]:
    return dict(_rendered())


def test_rendered_pages_pass():
    files = rendered()
    assert COUNTER.search(files["index.html"]), "the home page should still carry the counter"
    assert problems(files) == []


def test_published_files_match_the_build():
    for rel, text in rendered().items():
        if rel.split("/")[0] in LEGAL:
            assert (SITE / rel).read_text() == text, rel


def test_grid_foot_links_both_pages():
    for rel in ("site/grid/index.html", "site/grid/template.html"):
        grid_foot = (ROOT / rel).read_text().split('<footer id="foot">', 1)[1].split("</footer>", 1)[0]
        assert '<a href="../privacy/">Privacy</a>' in grid_foot and '<a href="../terms/">Terms</a>' in grid_foot, rel


def test_each_page_links_the_other_and_marks_itself():
    files = rendered()
    for p in LEGAL:
        f = foot(files[f"{p}/index.html"])
        assert f'<a href="../{p}/" aria-current="page">' in f
        other = next(x for x in LEGAL if x != p)
        assert f'<a href="../{other}/">' in f


def test_last_updated_is_fixed_not_the_feed_date():
    feed = pages.load(SITE / "v1")
    feed2 = dict(feed, date="2030-01-01")
    a = pages.legal_files((SITE / "index.html").read_text())
    assert pages.sitemap(feed2).count(f"<lastmod>{pages.LEGAL_UPDATED}</lastmod>") >= 4
    assert f"Last updated: {pages.day(pages.LEGAL_UPDATED)}" in a["privacy/index.md"]


def test_no_page_names_a_person_or_the_counter_account():
    """The only name is the one in LICENSE, and the pages link that file instead of typing it."""
    account = pages.load_config(SITE)["counter"]["code"]
    holder = re.search(r"Copyright \(c\) \d{4} (.+)", (ROOT / "LICENSE").read_text()).group(1).strip()
    files = rendered()
    for p in LEGAL:
        for t in ("index.html", "index.md"):
            text = files[f"{p}/{t}"]
            assert f"{account}.goatcounter" not in text and holder not in text and holder.split()[-1] not in text
    assert pages.LICENSE_URL in files["terms/index.html"]


@pytest.mark.parametrize("p", LEGAL)
def test_each_page_stays_short(p):
    words = len(re.findall(r"\S+", rendered()[f"{p}/index.md"]))
    assert words < 450, words


# ---------- planted failures: each check catches its own break ----------

def planted(change) -> list[str]:
    files = rendered()
    change(files)
    return problems(files)


def test_planted_missing_page():
    assert "terms/index.md missing" in planted(lambda f: f.pop("terms/index.md"))


def test_planted_missing_home_link():
    assert "home foot has no link to privacy/" in planted(
        lambda f: f.update({"index.html": f["index.html"].replace('<a href="privacy/">Privacy</a>', "Privacy")}))


def test_planted_missing_sitemap_entry():
    assert f"sitemap lacks terms/" in planted(
        lambda f: f.update({"sitemap.xml": f["sitemap.xml"].replace(f"<loc>{HOME}terms/</loc>", "")}))


def test_planted_counter_script():
    tag = pages.counter_tag(pages.load_config(SITE))
    assert "privacy/index.html carries a counter script" in planted(
        lambda f: f.update({"privacy/index.html": f["privacy/index.html"].replace("</body>", tag + "</body>")}))


def test_planted_missing_not_advice():
    assert f"terms/index.html lacks: {pages.NOT_ADVICE}" in planted(
        lambda f: f.update({"terms/index.html": f["terms/index.html"].replace(pages.NOT_ADVICE, "It is free.")}))


def test_planted_missing_disclosure():
    assert f"terms/index.md lacks: {pages.DISCLOSURE}" in planted(
        lambda f: f.update({"terms/index.md": f["terms/index.md"].replace(pages.DISCLOSURE, "")}))


def test_planted_missing_twin_in_llms():
    assert "llms.txt lacks privacy/index.md" in planted(
        lambda f: f.update({"llms.txt": f["llms.txt"].replace(f"{HOME}privacy/index.md", "")}))


def test_planted_overclaim():
    assert "privacy/index.md claims 'GDPR'" in planted(
        lambda f: f.update({"privacy/index.md": f["privacy/index.md"] + "\nDATproof is GDPR ready.\n"}))
