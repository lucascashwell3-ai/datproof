"""On-chain signals module: offline, deterministic, unavailable-before-guess."""

import json

import pytest

from datproof.onchain_signals import (
    METRICS,
    MetricSpec,
    _extract,
    interpret,
    load_signals,
)


def test_extract_ignores_timestamp_fields():
    # Real shape from the API: {"d","unixTs","<slug>"} — take the metric field.
    value, as_of = _extract({"d": "2026-07-10", "unixTs": 1783641600, "sopr": 0.9832})
    assert value == pytest.approx(0.9832)
    assert as_of == "2026-07-10"


def test_extract_raises_when_no_value():
    with pytest.raises(ValueError):
        _extract({"d": "2026-07-10", "unixTs": 1783641600})


def test_interpret_directions():
    sil = next(m for m in METRICS if m.key == "supply_in_loss")
    mvrv = next(m for m in METRICS if m.key == "mvrv")
    sopr = next(m for m in METRICS if m.key == "sopr")
    # supply-in-loss: high = fear, low = euphoria
    assert "accumulation" in interpret(sil, 60)
    assert "euphoria" in interpret(sil, 5)
    # MVRV < 1 = holders underwater; high = euphoric
    assert "underwater" in interpret(mvrv, 0.9)
    assert "euphoric" in interpret(mvrv, 3.5)
    # SOPR < 1 = selling at a loss
    assert "capitulation" in interpret(sopr, 0.98)
    assert "profit" in interpret(sopr, 1.02)


def test_load_from_cache_offline(tmp_path):
    cache = tmp_path / "onchain_signals.json"
    cache.write_text(json.dumps({
        "as_of": "2026-07-11T00:00:00Z",
        "signals": {
            "mvrv": {"value": 1.4, "as_of": "2026-07-10"},
            "sopr": {"value": 0.99, "as_of": "2026-07-10"},
        },
    }))
    ctx = load_signals(cache_file=cache, allow_network=False)
    assert ctx is not None
    assert ctx.source == "cached-snapshot"
    keys = {s.key for s in ctx.signals}
    assert keys == {"mvrv", "sopr"}
    mvrv = next(s for s in ctx.signals if s.key == "mvrv")
    assert mvrv.value == pytest.approx(1.4)
    assert mvrv.reading  # non-empty interpretation


def test_unavailable_when_no_cache_and_offline(tmp_path):
    ctx = load_signals(cache_file=tmp_path / "missing.json", allow_network=False)
    assert ctx is None  # -> tearsheet renders explicit "unavailable", never a guess


def test_signals_preserve_display_order(tmp_path):
    cache = tmp_path / "onchain_signals.json"
    cache.write_text(json.dumps({
        "as_of": "2026-07-11T00:00:00Z",
        "signals": {  # deliberately out of display order
            "sopr": {"value": 0.99, "as_of": "2026-07-10"},
            "supply_in_loss": {"value": 62.0, "as_of": "2026-07-10"},
            "mvrv": {"value": 1.4, "as_of": "2026-07-10"},
        },
    }))
    ctx = load_signals(cache_file=cache, allow_network=False)
    assert [s.key for s in ctx.signals] == [m.key for m in METRICS]
