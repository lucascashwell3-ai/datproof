"""Where-to-buy file and link check, with a fake fetch (no network)."""
import json
from urllib.parse import urlparse

from datproof_feed import brokers as B


PAGE = "<html>STRC stretch preferred; SATA SATS Strive</html>"


def run(tmp_path, responses, old=None):
    out = tmp_path / "w.json"
    if old is not None:
        out.write_text(json.dumps(old))

    def get(url):
        r = responses(url) if callable(responses) else responses
        if isinstance(r, Exception):
            raise r
        return r
    code = B.main(["--out", str(out), "--date", "2026-11-28"], get=get)
    return code, json.loads(out.read_text())


def test_all_ok(tmp_path):
    code, doc = run(tmp_path, (200, PAGE))
    assert code == 0
    cells = [c for b in doc["brokers"] for c in b["tickers"].values() if c["url"]]
    assert len(cells) == 18 and all(c["status"] == "ok" and c["checked_on"] == "2026-11-28" for c in cells)
    assert doc["settlement"]["source"].startswith("https://www.finra.org/")


def test_403_and_bot_wall_are_not_failures(tmp_path):
    def resp(url):
        return (403, "") if "coinbase" in url else (200, "<title>Just a moment...</title>") if "kraken" in url else (200, PAGE)
    code, doc = run(tmp_path, resp)
    assert code == 0
    by = {b["name"]: b for b in doc["brokers"]}
    assert {c["status"] for c in by["Coinbase"]["tickers"].values()} == {"not checked by script"}
    assert {c["status"] for c in by["Kraken (US)"]["tickers"].values()} == {"not checked by script"}
    assert len(B.shown(doc)) == 7


def test_planted_404_drops_cell_and_exits_1(tmp_path):
    def resp(url):
        return (404, "") if url.endswith("/sata") else (200, PAGE)
    code, doc = run(tmp_path, resp)
    assert code == 1
    public = next(b for b in doc["brokers"] if b["name"] == "Public")
    assert public["tickers"]["SATA"]["status"] == "not found"
    shown = {b["name"]: b for b in B.shown(doc)}
    assert "SATA" not in shown["Public"]["tickers"] and "STRC" in shown["Public"]["tickers"]


def test_broker_with_no_shown_cell_drops_off(tmp_path):
    code, doc = run(tmp_path, lambda url: (410, "") if "webull" in url else (200, PAGE))
    assert code == 1
    assert "Webull" not in [b["name"] for b in B.shown(doc)]
    assert any(b["name"] == "Webull" for b in doc["brokers"])


def test_network_error_keeps_previous(tmp_path):
    _, first = run(tmp_path, (200, PAGE))
    code, doc = run(tmp_path, OSError("boom"), old=first)
    assert code == 1
    cell = doc["brokers"][0]["tickers"]["STRC"]
    assert cell["status"] == "ok" and cell["checked_on"] == "2026-11-28" and "boom" in cell["reason"]


def test_alphabetical_no_query_strings_and_ib_has_no_links(tmp_path):
    _, doc = run(tmp_path, (200, PAGE))
    names = [b["name"] for b in doc["brokers"]]
    assert names == sorted(names, key=str.lower)
    for b in doc["brokers"]:
        for c in b["tickers"].values():
            if c["url"]:
                u = urlparse(c["url"])
                assert not u.query and not u.fragment and u.scheme == "https"
    ib = next(b for b in doc["brokers"] if b["name"] == "Interactive Brokers")
    assert all(c["url"] is None and c["status"] == "named, no link" for c in ib["tickers"].values())


def test_committed_file_matches_code():
    doc = json.loads(B.FILE.read_text())
    fresh = B.fresh_doc(doc["checked_on"])
    for b, f in zip(doc["brokers"], fresh["brokers"]):
        assert b["name"] == f["name"]
        assert {t: c["url"] for t, c in b["tickers"].items()} == {t: c["url"] for t, c in f["tickers"].items()}


def test_generic_200_without_the_ticker_is_not_found(tmp_path):
    generic = "<html>Stocks you may like: stretch, strive, ZZZQQ</html>"  # echoes another ticker, not STRC
    code, doc = run(tmp_path, lambda url: (200, generic) if "coinbase" in url else (200, PAGE))
    assert code == 1
    cb = next(b for b in doc["brokers"] if b["name"] == "Coinbase")
    assert {c["status"] for c in cb["tickers"].values()} == {"not found"}
    assert "Coinbase" not in [b["name"] for b in B.shown(doc)]


def test_200_echoing_ticker_without_security_name_is_not_found(tmp_path):
    code, doc = run(tmp_path, lambda url: (200, "<html>STRC SATA SATS not available</html>") if "sofi" in url else (200, PAGE))
    assert code == 1
    assert "SoFi" not in [b["name"] for b in B.shown(doc)]
