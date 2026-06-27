"""
blockchain_fetcher.py

Fetches transaction history for ETH and BTC wallet addresses.
- ETH: Etherscan API (requires free API key)
- BTC: Blockstream API (no key required)

Returns normalized transaction data ready for risk analysis.
"""

import os
import httpx
from dotenv import load_dotenv
from dataclasses import dataclass, field
from typing import Optional

load_dotenv()

ETHERSCAN_API_KEY = os.getenv("ETHERSCAN_API_KEY")
ETHERSCAN_BASE = "https://api.etherscan.io/v2/api"  # Etherscan v2
ETHERSCAN_CHAIN_ID = 1  # 1 = Ethereum mainnet
BLOCKSTREAM_BASE = "https://blockstream.info/api"


@dataclass
class Transaction:
    tx_hash: str
    chain: str           # "ETH" or "BTC"
    from_address: str
    to_address: str
    value_native: float  # Amount in ETH or BTC (not wei/sats)
    value_usd: Optional[float]
    timestamp: int       # Unix timestamp
    block: int
    fee_native: Optional[float] = None
    confirmations: Optional[int] = None
    is_error: bool = False


@dataclass
class WalletProfile:
    address: str
    chain: str
    transactions: list[Transaction] = field(default_factory=list)
    total_received: float = 0.0
    total_sent: float = 0.0
    unique_counterparties: int = 0
    tx_count: int = 0
    error: Optional[str] = None


def detect_chain(address: str) -> str:
    """Detect whether an address is ETH or BTC based on format."""
    address = address.strip()
    if address.startswith("0x") and len(address) == 42:
        return "ETH"
    if address.startswith(("1", "3", "bc1")):
        return "BTC"
    raise ValueError(f"Unrecognized address format: {address}")


def fetch_eth_transactions(address: str, limit: int = 100) -> WalletProfile:
    """Fetch ETH transaction history from Etherscan."""
    if not ETHERSCAN_API_KEY:
        raise EnvironmentError("ETHERSCAN_API_KEY not set in .env")

    params = {
        "chainid": ETHERSCAN_CHAIN_ID,
        "module": "account",
        "action": "txlist",
        "address": address,
        "startblock": 0,
        "endblock": 99999999,
        "page": 1,
        "offset": limit,
        "sort": "desc",
        "apikey": ETHERSCAN_API_KEY,
    }

    response = httpx.get(ETHERSCAN_BASE, params=params, timeout=15)
    response.raise_for_status()
    data = response.json()

    if data["status"] == "0" and data["message"] != "No transactions found":
        return WalletProfile(address=address, chain="ETH", error=data.get("result", "Etherscan error"))

    raw_txs = data.get("result", [])
    if not isinstance(raw_txs, list):
        return WalletProfile(address=address, chain="ETH", error="Unexpected Etherscan response")

    transactions = []
    total_received = 0.0
    total_sent = 0.0
    counterparties = set()

    for tx in raw_txs:
        value_eth = int(tx.get("value", 0)) / 1e18
        gas_price = int(tx.get("gasPrice", 0))
        gas_used = int(tx.get("gasUsed", 0))
        fee_eth = (gas_price * gas_used) / 1e18
        from_addr = tx.get("from", "").lower()
        to_addr = tx.get("to", "").lower()

        t = Transaction(
            tx_hash=tx.get("hash", ""),
            chain="ETH",
            from_address=from_addr,
            to_address=to_addr,
            value_native=value_eth,
            value_usd=None,  # Price lookup can be added later
            timestamp=int(tx.get("timeStamp", 0)),
            block=int(tx.get("blockNumber", 0)),
            fee_native=fee_eth,
            confirmations=int(tx.get("confirmations", 0)),
            is_error=tx.get("isError") == "1",
        )
        transactions.append(t)

        if from_addr == address.lower():
            total_sent += value_eth
            counterparties.add(to_addr)
        else:
            total_received += value_eth
            counterparties.add(from_addr)

    return WalletProfile(
        address=address,
        chain="ETH",
        transactions=transactions,
        total_received=total_received,
        total_sent=total_sent,
        unique_counterparties=len(counterparties),
        tx_count=len(transactions),
    )


def fetch_btc_transactions(address: str, limit: int = 50) -> WalletProfile:
    """Fetch BTC transaction history from Blockstream (no API key required)."""
    url = f"{BLOCKSTREAM_BASE}/address/{address}/txs"

    response = httpx.get(url, timeout=15)
    if response.status_code == 400:
        return WalletProfile(address=address, chain="BTC", error="Invalid BTC address")
    response.raise_for_status()

    raw_txs = response.json()[:limit]
    transactions = []
    total_received = 0.0
    total_sent = 0.0
    counterparties = set()

    for tx in raw_txs:
        # Sum inputs from this address
        sent_sats = sum(
            inp.get("prevout", {}).get("value", 0)
            for inp in tx.get("vin", [])
            if inp.get("prevout", {}).get("scriptpubkey_address") == address
        )
        # Sum outputs to this address
        received_sats = sum(
            out.get("value", 0)
            for out in tx.get("vout", [])
            if out.get("scriptpubkey_address") == address
        )

        value_btc = (received_sats - sent_sats) / 1e8
        status = tx.get("status", {})

        # Collect counterparty addresses
        for out in tx.get("vout", []):
            addr = out.get("scriptpubkey_address")
            if addr and addr != address:
                counterparties.add(addr)

        t = Transaction(
            tx_hash=tx.get("txid", ""),
            chain="BTC",
            from_address=address if sent_sats > 0 else "external",
            to_address=address if received_sats > 0 else "external",
            value_native=abs(value_btc),
            value_usd=None,
            timestamp=status.get("block_time", 0),
            block=status.get("block_height", 0),
            confirmations=None,
            is_error=False,
        )
        transactions.append(t)

        if sent_sats > 0:
            total_sent += sent_sats / 1e8
        if received_sats > 0:
            total_received += received_sats / 1e8

    return WalletProfile(
        address=address,
        chain="BTC",
        transactions=transactions,
        total_received=total_received,
        total_sent=total_sent,
        unique_counterparties=len(counterparties),
        tx_count=len(transactions),
    )


def fetch_wallet(address: str, limit: int = 100) -> WalletProfile:
    """Main entry point. Auto-detects chain and fetches transactions."""
    address = address.strip()
    chain = detect_chain(address)
    if chain == "ETH":
        return fetch_eth_transactions(address, limit=limit)
    elif chain == "BTC":
        return fetch_btc_transactions(address, limit=limit)
    else:
        raise ValueError(f"Unsupported chain: {chain}")
