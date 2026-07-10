"""Long-horizon BTC cycle context: 200-week moving average, ATH drawdown,
and DAT cost basis vs the long-term trend.

Same evidence discipline as the rest of the pipeline: keyless Coinbase
Exchange candles, committed cache fallback for offline/CI, every output
labeled with as_of + source. Insufficient history raises — never estimated.

Conventions: weekly close = last daily close per ISO week (Mon-Sun);
200WMA = simple average of the latest 200 weekly closes (incl. in-progress
week); ATH is close-based.
"""

from dataclasses import dataclass
from datetime import date
from itertools import groupby


@dataclass
class PricePoint:
    date: str          # ISO date, UTC
    close_usd: float


def weekly_closes(daily: list[PricePoint]) -> list[PricePoint]:
    """Last daily close of each ISO week, ascending by date."""
    ordered = sorted(daily, key=lambda p: p.date)

    def iso_week(p: PricePoint) -> tuple[int, int]:
        return date.fromisoformat(p.date).isocalendar()[:2]

    return [list(group)[-1] for _, group in groupby(ordered, key=iso_week)]


@dataclass
class CycleContext:
    as_of: str
    source: str                 # "coinbase-live" | "cached-snapshot"
    spot_usd: float
    wma_200w_usd: float
    price_to_200wma: float
    ath_usd: float
    ath_date: str
    drawdown_from_ath_pct: float    # signed; 0 at ATH
    weeks_of_history: int


def compute_cycle_context(daily: list[PricePoint], spot_usd: float,
                          as_of: str, source: str) -> CycleContext:
    weeks = weekly_closes(daily)
    if len(weeks) < 200:
        raise ValueError(f"insufficient history: need 200 weekly closes, got {len(weeks)}")
    wma = sum(p.close_usd for p in weeks[-200:]) / 200
    ath = max(daily, key=lambda p: p.close_usd)
    return CycleContext(
        as_of=as_of,
        source=source,
        spot_usd=spot_usd,
        wma_200w_usd=wma,
        price_to_200wma=spot_usd / wma,
        ath_usd=ath.close_usd,
        ath_date=ath.date,
        drawdown_from_ath_pct=(spot_usd - ath.close_usd) / ath.close_usd * 100,
        weeks_of_history=len(weeks),
    )
