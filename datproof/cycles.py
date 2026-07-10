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
