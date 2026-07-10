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

from .registry import Registry

BTC_MAX_SUPPLY = 21_000_000  # protocol constant — the one figure needing no source


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


@dataclass
class CostBasisContext:
    company_id: str
    name: str
    avg_cost_usd: float
    cost_to_200wma: float
    bought_above_trend: bool


def cost_basis_vs_200wma(registry: Registry, ctx: CycleContext) -> list[CostBasisContext]:
    """Disclosed average cost vs the 200WMA — who bought above the long-term trend."""
    rows = [
        CostBasisContext(
            company_id=c.id,
            name=c.name,
            avg_cost_usd=c.avg_cost_usd,
            cost_to_200wma=c.avg_cost_usd / ctx.wma_200w_usd,
            bought_above_trend=c.avg_cost_usd > ctx.wma_200w_usd,
        )
        for c in registry.companies
        if c.avg_cost_usd is not None and c.avg_cost_usd > 0
    ]
    rows.sort(key=lambda r: r.cost_to_200wma, reverse=True)
    return rows


def adoption_share_of_max_supply_pct(registry: Registry) -> float:
    return registry.total_btc / BTC_MAX_SUPPLY * 100
