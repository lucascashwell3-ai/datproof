"""Write the public /v1/ files from a day's snapshot.

    instruments.json          the snapshot without the dividend lists and daily closes, plus each
                              instrument's hold odds for 7, 30, 90, 180 and 365 days, and the same
                              holds split by the price paid (by_buy_price), and the bitcoin
                              crash test (backing) for each Strategy and Strive preferred
    instrument/<TICKER>.json  one instrument, with its dividends, daily closes and hold odds
    changes.json              what changed day to day, newest first, 90 entries at most
    method.json               every formula, flag and source in plain words (from compare.METHOD
                              and scenarios.METHOD)
    scenarios.json            past windows and three named situations (from scenarios.build)

status.json and days/<date>.json are written by build.py.
"""
from __future__ import annotations

import json
import pathlib

from datproof_feed import backing, scenarios, sources
from datproof_feed.compare import METHOD, _tbill_pct, buy_price_table, hold_odds_table, sharpe_table

MAX_CHANGES = 90
DATA = pathlib.Path(__file__).resolve().parents[1] / "data"
LISTINGS_FILE = DATA / "instrument_listings.json"
RATES_FILE = DATA / "comparison_rates.json"      # written daily by python -m datproof_feed.rates
BROKERS_FILE = DATA / "where_to_buy.json"        # written daily by python -m datproof_feed.brokers
PROFILES_FILE = DATA / "instrument_profiles.json"  # tax_statements: issuers' and the IRS's own words
RATE_RESET_DAYS = 35  # a monthly-reset rate is only out of date once a reset has been missed
STALE_DAYS = 4


def _days(a: str, b: str) -> int:
    import datetime as dt
    return (dt.date.fromisoformat(str(b)[:10]) - dt.date.fromisoformat(str(a)[:10])).days


def tidy(ins: dict, date: str, listings: dict) -> dict:
    """Facts the day file states too bluntly, set right at publish time:
    - a monthly-reset rate (variable rate, set by the issuer each month) is not out of date between resets;
    - a fixed-rate issue is flagged fixed_rate, not issuer_sets_rate;
    - the 30-day average trading value in dollars;
    - where the issue is listed and its full security name."""
    ins = {**ins}
    prof = ins.get("profile") or {}
    rate_type = (prof.get("rate_type") or {}).get("value")
    rate = ins.get("stated_rate_pct")
    if isinstance(rate, dict) and rate.get("as_of") and rate_type == "variable" and ins.get("issuer") == "Strive":
        rate = {**rate, "rate_set_on": rate["as_of"], "stale": _days(rate["as_of"], date) > RATE_RESET_DAYS}
        ins["stated_rate_pct"] = rate
        y = ins.get("yield_pct")
        if isinstance(y, dict):
            close = ins.get("close_usd") or {}
            ins["yield_pct"] = {**y, "stale": bool(rate["stale"] or close.get("stale"))}
    flags = list(ins.get("flags") or [])
    if rate_type == "fixed":
        flags = ["fixed_rate" if f == "issuer_sets_rate" else f for f in flags]
    if "stale" in flags and not any(isinstance(v, dict) and v.get("stale") for v in ins.values()):
        flags.remove("stale")
    ins["flags"] = flags
    vol, close = ins.get("avg_volume_30d"), ins.get("close_usd")
    if isinstance(vol, dict) and isinstance(close, dict):
        v = vol.get("value") * close.get("value") if vol.get("value") is not None and close.get("value") is not None else None
        ins["avg_value_30d_usd"] = {"value": round(v) if v is not None else None, "unit": "usd",
                                    "formula": "avg_volume_30d * close_usd", "inputs": ["avg_volume_30d", "close_usd"],
                                    "as_of": vol.get("as_of"), "stale": bool(vol.get("stale")),
                                    "reason": None if v is not None else "volume or close not available"}
    lst = (listings.get("instruments") or {}).get(ins.get("ticker"))
    if lst:
        ins["listing"] = {**lst, "fetched_at": listings.get("read_on")}
    pay = ins.get("payments") or {}
    if pay.get("in_a_row") and "since" not in pay and ins.get("dividends"):
        # a day file written before payments.since existed: the same count, from its own dividend list
        import datetime as _dt
        divs = [(_dt.date.fromisoformat(d["ex"]), _dt.date.fromisoformat(d["pay"]), d["usd"]) for d in ins["dividends"]]
        gap = sources.QUARTERLY_MAX_GAP if ins.get("schedule") == "quarterly" else 35
        again = sources.streak(divs, _dt.date.fromisoformat(date), gap)
        if again["in_a_row"] == pay["in_a_row"]:
            ins["payments"] = {**pay, "since": again["since"], "schedules": again["schedules"]}
    return ins


def _read(path: pathlib.Path) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception:  # noqa: BLE001 - side files are extra; their absence must not stop the feed
        return {}


def side_files() -> dict:
    """The dated side files joined into instruments.json: comparison rates, where to buy, tax statements.
    Each keeps its own dates; a missing file leaves its key out."""
    from datproof_feed import brokers
    out = {}
    rates = _read(RATES_FILE)
    if rates.get("rates"):
        out["comparison_rates"] = {"fetched_at": rates.get("fetched_at"), "rates": rates["rates"],
                                   "failed_checks": rates.get("failed_checks") or []}
    buy = _read(BROKERS_FILE)
    if buy.get("brokers"):
        out["where_to_buy"] = {"checked_on": buy.get("checked_on"), "tickers": buy.get("tickers"),
                               "settlement": buy.get("settlement"), "brokers": brokers.shown(buy)}
    static = _read(DATA / "backing_static.json").get("comparison")
    if static:
        out["_backing_comparison"] = static
    prof = _read(PROFILES_FILE)
    for key in ("tax_statements", "insurance"):
        if prof.get(key):
            out[key] = prof[key]
    return out


def _coverage_meanings(snap: dict) -> dict:
    cov = snap.get("coverage")
    if not isinstance(cov, dict):
        return snap
    issuers = []
    for c in cov.get("issuers") or []:
        c = {**c}
        y = c.get("years_of_dividends_covered")
        if isinstance(y, dict):
            c["years_of_dividends_covered"] = {**y, "meaning": (
                "the issuer's own figure: years of dividends its bitcoin and cash together would pay at today's "
                "bitcoin price. Not the same as backing.cash_years, which counts only cash set aside.")}
        issuers.append(c)
    return {**snap, "coverage": {**cov, "issuers": issuers}}


def _dump(obj) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False) + "\n"


def _v(x):
    return x.get("value") if isinstance(x, dict) else x


def _ok(state) -> str:
    return "ok" if state == "ok" else "failed"


def diff(prev: dict | None, cur: dict) -> list[dict]:
    """Changes from the previous snapshot to this one, in a fixed order."""
    if not prev:
        return []
    out = []
    date = cur["date"]
    before = {i["ticker"]: i for i in prev.get("instruments", [])}
    for ins in cur.get("instruments", []):
        old = before.get(ins["ticker"])
        if old is None:
            continue
        for field in ("stated_rate_pct", "schedule"):
            a, b = _v(old.get(field)), _v(ins.get(field))
            if a != b and a is not None and b is not None:
                out.append({"date": date, "ticker": ins["ticker"], "field": field, "from": a, "to": b})
        seen = {json.dumps(g, sort_keys=True) for g in (old.get("payments") or {}).get("gaps", [])}
        for g in (ins.get("payments") or {}).get("gaps", []):
            if json.dumps(g, sort_keys=True) not in seen:
                out.append({"date": date, "ticker": ins["ticker"], "field": "payments.gaps",
                            "from": None, "to": g})
    old_src, new_src = prev.get("sources", {}), cur.get("sources", {})
    for name in sorted(new_src):
        if name in old_src and _ok(old_src[name]) != _ok(new_src[name]):
            out.append({"date": date, "ticker": None, "field": f"sources.{name}",
                        "from": _ok(old_src[name]), "to": _ok(new_src[name])})
    return out


def publish(snap: dict, out, prev: dict | None) -> None:
    """Write instruments.json, instrument/<T>.json, changes.json, method.json and scenarios.json
    under `out`.
    Re-running for the same day replaces that day's change entries instead of adding them twice."""
    out = pathlib.Path(out)
    (out / "instrument").mkdir(parents=True, exist_ok=True)

    tbill = _tbill_pct(snap)
    crash = backing.table(snap.get("backing"))
    try:
        listings = json.loads(LISTINGS_FILE.read_text())
    except Exception:  # noqa: BLE001 - listings are extra; their absence must not stop the feed
        listings = {}
    snap = _coverage_meanings({**snap, "instruments": [tidy(i, snap["date"], listings) for i in snap.get("instruments", [])]})
    side = side_files()
    cmp_rows = side.pop("_backing_comparison", None)
    if cmp_rows and isinstance(snap.get("backing"), dict) and isinstance(snap["backing"].get("static"), dict):
        # the comparison rows are reference figures, not day data: the current file wins
        snap = {**snap, "backing": {**snap["backing"], "static": {**snap["backing"]["static"], "comparison": cmp_rows}}}
    snap = {**snap, **side}
    full = [{**i, "hold_odds": hold_odds_table(i, tbill), "by_buy_price": buy_price_table(i),
             "sharpe": sharpe_table(i, tbill),
             **({"backing": crash[i["ticker"]]} if i["ticker"] in crash else {})}
            for i in snap.get("instruments", [])]
    lean = {**snap, "instruments": [{k: v for k, v in i.items() if k not in ("dividends", "closes")}
                                    for i in full]}
    if lean.get("comparison_rates"):
        from datproof_feed.compare import situation
        lean["situation_default"] = situation(lean)  # the worked example the page writes in
    (out / "instruments.json").write_text(_dump(lean))
    for ins in full:
        (out / "instrument" / f"{ins['ticker']}.json").write_text(_dump({"date": snap["date"], **ins}))

    path = out / "changes.json"
    older = json.loads(path.read_text()) if path.exists() else []
    older = [c for c in older if c.get("date") != snap["date"]]
    (out / "changes.json").write_text(_dump((diff(prev, snap) + older)[:MAX_CHANGES]))

    method = {**METHOD, "formulas": {**METHOD.get("formulas", {}), "payments_since": sources.PAYMENTS_SINCE_METHOD}}
    (out / "method.json").write_text(_dump({**method, "scenarios": scenarios.METHOD}))
    (out / "scenarios.json").write_text(_dump(scenarios.build(snap)))


def previous_day(days_dir, date: str) -> dict | None:
    """The newest day file dated before `date`, or None."""
    days_dir = pathlib.Path(days_dir)
    names = sorted(p.name for p in days_dir.glob("????-??-??.json") if p.stem < date)
    return json.loads((days_dir / names[-1]).read_text()) if names else None
