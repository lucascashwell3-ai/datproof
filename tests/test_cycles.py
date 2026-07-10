import pytest

from datproof.cycles import PricePoint, compute_cycle_context, weekly_closes


def daily(*pairs):
    return [PricePoint(date=d, close_usd=c) for d, c in pairs]


def test_weekly_resample_takes_last_close_of_each_iso_week():
    # 2026-06-29 is a Monday; two ISO weeks with 3 and 2 daily closes
    series = daily(("2026-06-29", 100.0), ("2026-06-30", 101.0), ("2026-07-03", 102.0),
                   ("2026-07-06", 110.0), ("2026-07-07", 111.0))
    weeks = weekly_closes(series)
    assert [(p.date, p.close_usd) for p in weeks] == [
        ("2026-07-03", 102.0), ("2026-07-07", 111.0)]


def test_weekly_resample_handles_unsorted_input():
    series = daily(("2026-07-07", 111.0), ("2026-06-29", 100.0), ("2026-07-03", 102.0))
    weeks = weekly_closes(series)
    assert [p.close_usd for p in weeks] == [102.0, 111.0]


def synthetic_history(n_weeks=210, close=50_000.0):
    """n_weeks of Monday closes ending 2026-07-06, with one ATH spike."""
    from datetime import date, timedelta
    last = date(2026, 7, 6)
    pts = [PricePoint(date=(last - timedelta(weeks=n_weeks - 1 - i)).isoformat(),
                      close_usd=close) for i in range(n_weeks)]
    pts[-10] = PricePoint(date=pts[-10].date, close_usd=100_000.0)  # ATH spike
    return pts


def test_200wma_and_multiple_on_flat_series():
    pts = synthetic_history()
    ctx = compute_cycle_context(pts, spot_usd=60_000.0, as_of="2026-07-10", source="test")
    # 199 weeks at 50k + one 100k spike inside the 200-week window
    assert ctx.wma_200w_usd == pytest.approx((199 * 50_000 + 100_000) / 200)
    assert ctx.price_to_200wma == pytest.approx(60_000.0 / ctx.wma_200w_usd)
    assert ctx.weeks_of_history == 210


def test_ath_and_drawdown_are_close_based():
    pts = synthetic_history()
    ctx = compute_cycle_context(pts, spot_usd=60_000.0, as_of="2026-07-10", source="test")
    assert ctx.ath_usd == 100_000.0
    assert ctx.drawdown_from_ath_pct == pytest.approx(-40.0)


def test_insufficient_history_raises():
    pts = synthetic_history(n_weeks=150)
    with pytest.raises(ValueError, match="200 weekly closes"):
        compute_cycle_context(pts, spot_usd=60_000.0, as_of="2026-07-10", source="test")


def company(cid, btc, avg_cost):
    from datproof.registry import Company
    return Company(id=cid, name=cid.upper(), ticker=cid.upper(), exchange="NASDAQ",
                   btc_holdings=btc, avg_cost_usd=avg_cost, cost_basis_usd=None,
                   as_of="2026-07-01", source="test", disclosure_method="press release")


def registry_of(*companies):
    from datproof.registry import Registry
    return Registry(companies=list(companies), snapshot_date="2026-07-01",
                    btc_spot_snapshot_usd=60_000.0, btc_spot_snapshot_as_of="2026-07-01")


def test_cost_basis_vs_trend_flags_above_trend_buyers():
    from datproof.cycles import cost_basis_vs_200wma
    pts = synthetic_history(n_weeks=200, close=50_000.0)
    pts[-10] = PricePoint(date=pts[-10].date, close_usd=50_000.0)  # flat: WMA = 50k
    ctx = compute_cycle_context(pts, spot_usd=60_000.0, as_of="2026-07-10", source="test")
    reg = registry_of(company("hot", 100.0, 75_000.0),
                      company("humble", 50.0, 25_000.0),
                      company("undisclosed", 10.0, None))
    rows = cost_basis_vs_200wma(reg, ctx)
    assert [r.company_id for r in rows] == ["hot", "humble"]  # None skipped, desc by ratio
    assert rows[0].cost_to_200wma == pytest.approx(1.5) and rows[0].bought_above_trend
    assert rows[1].cost_to_200wma == pytest.approx(0.5) and not rows[1].bought_above_trend


def test_adoption_share_of_max_supply():
    from datproof.cycles import adoption_share_of_max_supply_pct
    reg = registry_of(company("a", 1_050_000.0, None))
    assert adoption_share_of_max_supply_pct(reg) == pytest.approx(5.0)


def write_cache(path, closes, as_of="2026-07-08T00:00:00Z"):
    import json
    path.write_text(json.dumps({
        "as_of": as_of,
        "source_note": "test",
        "daily_closes": [{"date": p.date, "close_usd": p.close_usd} for p in closes],
    }))


def test_load_price_history_offline_uses_cache(tmp_path):
    from datproof import cycles
    cache = tmp_path / "price_history.json"
    write_cache(cache, [PricePoint("2026-07-07", 60_000.0)])
    daily_pts, source, as_of = cycles.load_price_history(cache_file=cache, allow_network=False)
    assert [p.close_usd for p in daily_pts] == [60_000.0]
    assert source == "cached-snapshot" and as_of == "2026-07-08T00:00:00Z"


def test_load_price_history_tops_up_and_merges(tmp_path, monkeypatch):
    from datproof import cycles
    cache = tmp_path / "price_history.json"
    write_cache(cache, [PricePoint("2026-07-07", 60_000.0)])
    monkeypatch.setattr(cycles, "fetch_daily_closes",
                        lambda start, end: [PricePoint("2026-07-07", 60_000.0),
                                            PricePoint("2026-07-09", 61_000.0)])
    daily_pts, source, _ = cycles.load_price_history(cache_file=cache)
    assert [p.date for p in daily_pts] == ["2026-07-07", "2026-07-09"]  # merged, deduped
    assert source == "coinbase-live"
    assert "2026-07-09" in cache.read_text()  # cache updated


def test_load_price_history_network_failure_falls_back(tmp_path, monkeypatch):
    from datproof import cycles
    cache = tmp_path / "price_history.json"
    write_cache(cache, [PricePoint("2026-07-07", 60_000.0)])

    def boom(start, end):
        raise RuntimeError("offline")

    monkeypatch.setattr(cycles, "fetch_daily_closes", boom)
    daily_pts, source, _ = cycles.load_price_history(cache_file=cache)
    assert source == "cached-snapshot" and len(daily_pts) == 1


def test_load_price_history_missing_cache_and_no_network_raises(tmp_path):
    from datproof import cycles
    with pytest.raises(ValueError, match="no cached price history"):
        cycles.load_price_history(cache_file=tmp_path / "nope.json", allow_network=False)
