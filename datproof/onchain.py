"""On-chain balance verification and BTC spot price.

Live sources (both keyless):
- Blockstream API for BTC address balances
- Coinbase API for BTC spot price

Every fetch falls back to the cached snapshot in data/onchain_cache.json, so
the full pipeline runs in offline/CI environments; results are labeled with
their evidence source ("live" vs "cached") so nothing stale masquerades as
fresh.
"""

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import httpx

BLOCKSTREAM_BASE = "https://blockstream.info/api"
COINBASE_SPOT_URL = "https://api.coinbase.com/v2/prices/BTC-USD/spot"
CACHE_FILE = Path(__file__).parent / "data" / "onchain_cache.json"
SATS_PER_BTC = 100_000_000


@dataclass
class SpotPrice:
    usd: float
    as_of: str          # ISO date or datetime
    source: str         # "coinbase-live" | "cached-snapshot" | "override"


@dataclass
class AddressBalance:
    address: str
    btc: Optional[float]
    source: str         # "blockstream-live" | "cached" | "unavailable"
    error: Optional[str] = None


def _load_cache() -> dict:
    if CACHE_FILE.exists():
        return json.loads(CACHE_FILE.read_text())
    return {"spot": None, "addresses": {}}


def _save_cache(cache: dict) -> None:
    CACHE_FILE.write_text(json.dumps(cache, indent=2))


def get_spot_price(override: Optional[float] = None,
                   fallback_usd: float = 61600,
                   fallback_as_of: str = "2026-07-03") -> SpotPrice:
    """BTC spot in USD. Order: explicit override > live Coinbase > cache > registry snapshot."""
    if override is not None:
        return SpotPrice(usd=override, as_of="now", source="override")

    try:
        resp = httpx.get(COINBASE_SPOT_URL, timeout=10)
        resp.raise_for_status()
        usd = float(resp.json()["data"]["amount"])
        spot = SpotPrice(usd=usd, as_of=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                         source="coinbase-live")
        cache = _load_cache()
        cache["spot"] = {"usd": spot.usd, "as_of": spot.as_of}
        _save_cache(cache)
        return spot
    except Exception:
        pass

    cached = _load_cache().get("spot")
    if cached:
        return SpotPrice(usd=cached["usd"], as_of=cached["as_of"], source="cached-snapshot")
    return SpotPrice(usd=fallback_usd, as_of=fallback_as_of, source="cached-snapshot")


def get_address_balance(address: str) -> AddressBalance:
    """Confirmed BTC balance for an address via Blockstream, with cache fallback."""
    try:
        resp = httpx.get(f"{BLOCKSTREAM_BASE}/address/{address}", timeout=15)
        resp.raise_for_status()
        stats = resp.json()["chain_stats"]
        btc = (stats["funded_txo_sum"] - stats["spent_txo_sum"]) / SATS_PER_BTC
        cache = _load_cache()
        cache.setdefault("addresses", {})[address] = {
            "btc": btc,
            "as_of": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        _save_cache(cache)
        return AddressBalance(address=address, btc=btc, source="blockstream-live")
    except Exception as exc:
        cached = _load_cache().get("addresses", {}).get(address)
        if cached:
            return AddressBalance(address=address, btc=cached["btc"], source="cached")
        return AddressBalance(address=address, btc=None, source="unavailable", error=str(exc))


def verify_company_holdings(known_addresses: list[str],
                            disclosed_btc: float,
                            tolerance_pct: float = 1.0) -> dict:
    """Reconcile disclosed holdings against on-chain balances of published addresses.

    Returns a reconciliation result in audit terms: verified amount, coverage of
    the disclosed figure, and whether the difference exceeds tolerance.
    """
    balances = [get_address_balance(a) for a in known_addresses]
    resolved = [b for b in balances if b.btc is not None]
    verified_btc = sum(b.btc for b in resolved)
    coverage_pct = (verified_btc / disclosed_btc * 100) if disclosed_btc > 0 else 0.0
    return {
        "verified_btc": verified_btc,
        "coverage_pct": coverage_pct,
        "addresses_checked": len(balances),
        "addresses_resolved": len(resolved),
        "within_tolerance": abs(coverage_pct - 100.0) <= tolerance_pct if resolved else False,
        "balances": balances,
    }
