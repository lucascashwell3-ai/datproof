"""On-chain reality signals: sentiment (price) vs. the chain's own ledger.

Price is what the market *feels* a bitcoin is worth today. On-chain valuation
metrics — MVRV, SOPR, and the share of supply held at a loss — are what the
*chain* records about where holders actually bought. When the two diverge, the
gap is the story: capitulation when the market trades below aggregate cost
basis, euphoria when it trades far above.

Same evidence discipline as the rest of the pipeline (see ``cycles.py``):
keyless free API (bitcoin-data.com / BGeometrics), a committed cache fallback so
builds stay offline/CI-safe, every figure labeled with ``as_of`` + source, and —
critically — a metric with no sourced value renders *unavailable*, never a guess.
The free tier is rate-limited (10 req/hr); the nightly rebuild only needs one
call per metric, and deterministic builds never hit the network at all.
"""

import json
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

SIGNALS_CACHE_FILE = Path(__file__).parent / "data" / "onchain_signals.json"
API_BASE = "https://bitcoin-data.com/v1"
SOURCE_NAME = "bitcoin-data.com (BGeometrics)"


@dataclass(frozen=True)
class MetricSpec:
    key: str                              # internal id
    slug: str                             # single-endpoint slug (value used as-is); "" if computed
    label: str                            # display label
    unit: str                             # "%", "x", or ""
    lower_is_fear: bool                   # True: low value = fear (MVRV, SOPR); False: high = fear
    ratio_of: tuple[str, str] | None = None  # (numerator, denominator) slugs -> value = num/den*100


# All slugs verified against the bitcoin-data.com OpenAPI spec (2026-07-11).
# supply-in-loss has no direct percent endpoint, so it's computed supply-weighted
# (supply-loss / supply-current * 100) — the standard "% of supply in loss" definition.
# Order here is display order.
METRICS: tuple[MetricSpec, ...] = (
    MetricSpec("supply_in_loss", "", "Supply held at a loss", "%", lower_is_fear=False,
               ratio_of=("supply-loss", "supply-current")),
    MetricSpec("mvrv", "mvrv", "MVRV ratio", "x", lower_is_fear=True),
    MetricSpec("sopr", "sopr", "SOPR", "", lower_is_fear=True),
)


@dataclass
class Signal:
    key: str
    label: str
    unit: str
    value: float
    as_of: str          # ISO date the metric is "as of"
    reading: str        # plain-English interpretation (no jargon, no price call)


@dataclass
class SignalsContext:
    as_of: str          # when the cache/fetch was taken
    source: str         # "{SOURCE_NAME} (live)" | "cached-snapshot"
    signals: list[Signal]


def _extract(payload: dict) -> tuple[float, str]:
    """Pull (value, as_of_date) from a bitcoin-data.com point.

    Responses look like ``{"d": "2026-07-10", "unixTs": ..., "<slug>": 0.98}``.
    We take the one numeric field that isn't the timestamp, so we don't need to
    hard-code each metric's field name.
    """
    as_of = str(payload.get("d", ""))
    for k, v in payload.items():
        if k not in ("d", "unixTs") and isinstance(v, (int, float)):
            return float(v), as_of
    raise ValueError("no numeric metric value in payload")


def interpret(spec: MetricSpec, value: float) -> str:
    """Plain-English read. Describes on-chain state, never a price prediction."""
    if spec.key == "supply_in_loss":
        if value >= 50:
            return "over half of all coins are underwater — deep fear, historically an accumulation zone"
        if value >= 25:
            return "a meaningful share of supply is underwater — caution outweighs greed"
        if value >= 10:
            return "most coins are in profit — a broadly healthy, unstressed market"
        return "almost nothing is underwater — euphoria, historically a distribution zone"
    if spec.key == "mvrv":
        if value < 1:
            return "the market trades below aggregate on-chain cost basis — holders are, in total, underwater"
        if value < 2:
            return "the market sits modestly above what holders paid — fair-value territory, not frothy"
        if value < 3:
            return "the market trades well above aggregate cost basis — historically a heating-up phase"
        return "the market trades far above aggregate cost basis — historically euphoric"
    if spec.key == "sopr":
        if value < 1:
            return "coins moving on-chain are being spent at a loss on average — capitulation behavior"
        return "coins moving on-chain are being spent at a profit on average"
    return ""


def _fetch_last(slug: str, timeout: float) -> tuple[float, str] | None:
    resp = httpx.get(f"{API_BASE}/{slug}/last", timeout=timeout)
    if resp.status_code != 200:
        return None
    return _extract(resp.json())


def fetch_signal(spec: MetricSpec, *, timeout: float = 15.0) -> Signal | None:
    """Fetch one metric's latest point (or compute a supply-weighted ratio). Returns
    None on any failure — rate limit, 404, network, or an out-of-range ratio — so the
    caller renders it unavailable rather than fabricating."""
    try:
        if spec.ratio_of:
            num_slug, den_slug = spec.ratio_of
            num = _fetch_last(num_slug, timeout)
            den = _fetch_last(den_slug, timeout)
            if not num or not den or den[0] == 0:
                return None
            value, as_of = num[0] / den[0] * 100, num[1]
            if not 0 <= value <= 100:  # units sanity check — never render a nonsense %
                return None
        else:
            point = _fetch_last(spec.slug, timeout)
            if not point:
                return None
            value, as_of = point
    except (httpx.HTTPError, ValueError, KeyError):
        return None
    return Signal(spec.key, spec.label, spec.unit, value, as_of, interpret(spec, value))


def _write_cache(signals: list[Signal], as_of: str, cache_file: Path) -> None:
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps({
        "as_of": as_of,
        "source_note": f"{SOURCE_NAME} — latest on-chain valuation metrics",
        "signals": {s.key: {"value": s.value, "as_of": s.as_of} for s in signals},
    }, indent=1))


def _load_cache(cache_file: Path) -> tuple[list[Signal], str] | None:
    if not cache_file.exists():
        return None
    raw = json.loads(cache_file.read_text())
    by_key = raw.get("signals", {})
    out: list[Signal] = []
    for spec in METRICS:
        entry = by_key.get(spec.key)
        if entry is None:
            continue
        value = float(entry["value"])
        out.append(Signal(spec.key, spec.label, spec.unit, value,
                          str(entry.get("as_of", "")), interpret(spec, value)))
    if not out:
        return None
    return out, str(raw.get("as_of", ""))


def load_signals(cache_file: Path = SIGNALS_CACHE_FILE,
                 allow_network: bool = True) -> SignalsContext | None:
    """Cache-first on-chain signals. Returns None when nothing is available —
    the tearsheet then shows an explicit 'unavailable' state, never a guess.

    Live path fetches each metric, merges over the cache (so a single rate-limited
    metric keeps its last good value), and rewrites the cache. Offline/deterministic
    path uses the committed cache only.
    """
    cached = _load_cache(cache_file)

    if allow_network:
        fetched = [s for spec in METRICS if (s := fetch_signal(spec)) is not None]
        if fetched:
            merged: dict[str, Signal] = {s.key: s for s in (cached[0] if cached else [])}
            merged.update({s.key: s for s in fetched})
            ordered = [merged[spec.key] for spec in METRICS if spec.key in merged]
            as_of = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            _write_cache(ordered, as_of, cache_file)
            return SignalsContext(as_of=as_of, source=f"{SOURCE_NAME} (live)", signals=ordered)

    if cached is None:
        return None
    return SignalsContext(as_of=cached[1], source="cached-snapshot", signals=cached[0])
