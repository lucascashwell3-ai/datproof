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
