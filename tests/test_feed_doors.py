"""The first screen offers two actions, once each: see what you could earn, and connect your agent."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
MD = (ROOT / "site" / "index.md").read_text(encoding="utf-8")
HOME = "https://datproof.com/"


def hero() -> str:
    return HTML[HTML.index('<section class="wrap hero"'):HTML.index("</section>")]


def test_two_buttons_under_the_opening_paragraph_in_order():
    h = hero()
    doors = re.search(r'<p class="doors">(.*?)</p>', h, re.S)
    assert doors, "no buttons in the hero"
    assert h.index('class="hero-sub"') < h.index('class="doors"') < h.index('class="earn"')
    links = re.findall(r'<a class="([^"]+)" href="([^"]+)"[^>]*>([^<]+)</a>', doors.group(1))
    assert links == [("btn", "#calc", "See what you could earn"), ("btn btn-quiet", "#agent", "Connect your agent")]


def test_each_action_once_on_the_first_screen():
    top = HTML[:HTML.index('<section class="wrap block"')]  # header + hero
    assert top.count(">Connect your agent<") == 1
    assert top.count(">See what you could earn<") == 1
    header = HTML[HTML.index("<header"):HTML.index("</header>")]
    assert 'href="#agent"' not in header and 'class="mark"' in header


def test_targets_exist():
    assert 'id="calc"' in HTML and 'id="in-amount"' in HTML and 'id="agent"' in HTML
    calc = HTML[HTML.index('id="calc"'):]
    assert re.search(r"<(input|select)\b", calc).group(0) == "<input" and calc.index('id="in-amount"') < calc.index("<select")


def test_twin_carries_the_same_two_links_near_the_top():
    head = MD[:MD.index("\n## ")]
    assert f"[See what you could earn]({HOME}#calc)" in head
    assert f"[Connect your agent]({HOME}#agent)" in head
    assert head.index("See what you could earn") < head.index("Connect your agent](")


# ---------- the foot: one disclosure line beside "free, holds no money, places no orders, not advice" ----------

DISCLOSURE = "DATproof is not paid by any issuer or broker. Its maker holds some of the products shown."


def test_disclosure_once_in_the_foot_beside_the_statement():
    foot = HTML[HTML.index('<footer class="wrap foot">'):HTML.index("</footer>")]
    about = re.search(r'<ul class="about">(.*?)</ul>', foot, re.S).group(1)
    items = re.findall(r"<li>(.*?)</li>", about, re.S)
    i = items.index("It is free. It holds no money, places no orders and is not advice.")
    assert items[i + 1] == DISCLOSURE
    assert HTML.count(DISCLOSURE) == 1


def test_disclosure_in_the_twin_once():
    assert MD.count(DISCLOSURE) == 1
    assert "It is free. It holds no money, places no orders and is not advice. " + DISCLOSURE in MD


def test_disclosure_comes_from_the_page_source():
    from datproof_feed import pages
    assert pages.DISCLOSURE == DISCLOSURE and DISCLOSURE in pages.ABOUT and DISCLOSURE in pages.ABOUT_MD
