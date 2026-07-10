from datproof.cycles import PricePoint, weekly_closes


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
