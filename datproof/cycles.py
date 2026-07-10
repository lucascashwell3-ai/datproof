"""Long-horizon BTC cycle context: 200-week moving average, ATH drawdown,
and DAT cost basis vs the long-term trend.

Same evidence discipline as the rest of the pipeline: keyless Coinbase
Exchange candles, committed cache fallback for offline/CI, every output
labeled with as_of + source. Insufficient history raises — never estimated.

Conventions: weekly close = last daily close per ISO week (Mon-Sun);
200WMA = simple average of the latest 200 weekly closes (incl. in-progress
week); ATH is close-based.
"""

import json
import time
from dataclasses import dataclass
from datetime import date, timedelta
from itertools import groupby
from pathlib import Path

import httpx

from .registry import Registry

BTC_MAX_SUPPLY = 21_000_000  # protocol constant — the one figure needing no source
PRICE_CACHE_FILE = Path(__file__).parent / "data" / "price_history.json"
COINBASE_CANDLES_URL = "https://api.exchange.coinbase.com/products/BTC-USD/candles"
HISTORY_START = date(2022, 1, 1)   # ≥200 ISO weeks before mid-2026, with buffer


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


def fetch_daily_closes(start: date, end: date) -> list[PricePoint]:
    """Daily UTC closes from Coinbase Exchange, paginated (max 300 candles/call)."""
    points: dict[str, float] = {}
    window_start = start
    while window_start <= end:
        window_end = min(window_start + timedelta(days=299), end)
        resp = httpx.get(COINBASE_CANDLES_URL, params={
            "granularity": 86400,
            "start": window_start.isoformat(),
            "end": window_end.isoformat(),
        }, timeout=20)
        resp.raise_for_status()
        for ts, _low, _high, _open, close, _vol in resp.json():
            points[time.strftime("%Y-%m-%d", time.gmtime(ts))] = float(close)
        window_start = window_end + timedelta(days=1)
    return [PricePoint(date=d, close_usd=c) for d, c in sorted(points.items())]


def load_price_history(cache_file: Path = PRICE_CACHE_FILE,
                       allow_network: bool = True) -> tuple[list[PricePoint], str, str]:
    """Cache-first daily close history. Returns (daily_closes, source, as_of)."""
    cached: dict[str, float] = {}
    cached_as_of = None
    if cache_file.exists():
        raw = json.loads(cache_file.read_text())
        cached = {e["date"]: e["close_usd"] for e in raw["daily_closes"]}
        cached_as_of = raw["as_of"]

    if allow_network:
        try:
            start = date.fromisoformat(max(cached)) if cached else HISTORY_START
            fresh = fetch_daily_closes(start, date.fromtimestamp(time.time()))
            cached.update({p.date: p.close_usd for p in fresh})
            as_of = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps({
                "as_of": as_of,
                "source_note": "Coinbase Exchange daily candles (BTC-USD), UTC daily closes",
                "daily_closes": [{"date": d, "close_usd": c} for d, c in sorted(cached.items())],
            }, indent=1))
            return ([PricePoint(date=d, close_usd=c) for d, c in sorted(cached.items())],
                    "coinbase-live", as_of)
        except Exception:
            pass

    if not cached:
        raise ValueError("no cached price history and network unavailable/disallowed")
    return ([PricePoint(date=d, close_usd=c) for d, c in sorted(cached.items())],
            "cached-snapshot", cached_as_of)
