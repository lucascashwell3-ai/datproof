#!/usr/bin/env python3
"""MCP server: Bitcoin treasury filings for AI assistants.

Exposes a Bitcoin treasury company's SEC-filing ledger (built by
scripts/ledger_asst.py, see the datproof repo) as MCP tools, so any AI
assistant can answer questions about the filings with the filing attached —
every number in every response carries an accession number and a source URL.

Company today: Strive, Inc. (ASST common / SATA preferred). The design is
company-agnostic: every tool takes a `company` argument, resolved against a
small registry in ledger_client.py — adding a company means adding one
registry entry there, not touching any tool.

Data: the public ledger JSON at ledger_client.REGISTRY[company]["remote_base"],
read from the published site first and a local repo checkout as a fallback
(env var DATPROOF_LEDGER_DIR points at that checkout's ledger directory for a
company), cached in memory for the life of the process. See ledger_client.py.

Transport: stdio by default (Claude Desktop, Cursor, most local clients);
pass --http for streamable HTTP on a port instead.

Usage:
  datproof-agent                              # stdio
  datproof-agent --http                       # streamable HTTP on 127.0.0.1:8000
  datproof-agent --http --host 0.0.0.0 --port 9000
"""
from __future__ import annotations

import argparse
import json
from typing import Annotated, Any, Optional

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

import ledger_client as lc

mcp = FastMCP(
    "datproof_mcp",
    instructions=(
        "Answers questions about a Bitcoin treasury company's SEC filings, with the "
        "accession number and source URL attached to every figure. Start with "
        "list_companies() to see which companies are covered, then latest() for the "
        "newest snapshot or metric() for a single number. Nothing here is estimated: "
        "a value the filing didn't state comes back null with a note."
    ),
)

_READ_ONLY = ToolAnnotations(
    readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True
)

CompanyArg = Annotated[
    str, Field(description="Company code from list_companies(), e.g. 'asst' for Strive, Inc.")
]


def _ok(data: dict[str, Any]) -> str:
    return json.dumps(data, default=str)


def _err(e: Exception) -> str:
    return json.dumps({"error": str(e)})


@mcp.tool(name="list_companies", annotations=_READ_ONLY)
def list_companies() -> str:
    """List every company this agent has ledger data for.

    Returns:
        str: JSON — {"companies": [{"company","name","tickers","cik","remote_base"}, ...]}

    Example question: "Which companies does this cover?"
    """
    return _ok(lc.list_companies())


@mcp.tool(name="latest", annotations=_READ_ONLY)
def latest(company: CompanyArg) -> str:
    """The newest filing's full snapshot: every disclosed row (cash, bitcoin
    held, SATA/STRC, share counts), every derived metric, the verdict versus
    the prior filing, and reconciliation status.

    Args:
        company (str): company code, e.g. "asst"

    Returns:
        str: JSON — {"as_of","accession","filed","source_url","data_source",
        "btc_price_used","rows","metrics","verdict","reconciliation"}. A row
        the filing didn't state is null.

    Examples:
        - Use when: "What did Strive's latest 8-K disclose?"
        - Don't use when: you need one number only (use metric()) or a
          specific past filing (use filings() or metric(as_of=...)).
    """
    try:
        return _ok(lc.latest(company))
    except lc.LedgerError as e:
        return _err(e)


@mcp.tool(name="filings", annotations=_READ_ONLY)
def filings(
    company: CompanyArg,
    limit: Annotated[
        int, Field(ge=1, le=100, description="Max filings to return, newest first.")
    ] = 20,
) -> str:
    """List filings newest-first: filed date, accession, filing URL, BTC
    held, sats/share (effective), amplification, CEBE sats/share, the
    verdict versus the prior filing, and reconciliation flags — all at the
    ledger's current BTC price, so filings across time are compared on an
    apples-to-apples basis.

    Args:
        company (str): company code, e.g. "asst"
        limit (int): max filings to return (default 20, max 100)

    Returns:
        str: JSON — {"filings":[...], "count", "total_filings", "btc_price_used", ...}

    Examples:
        - Use when: "Show me Strive's last 5 weekly filings."
        - Don't use when: you want the full row/metric detail of one filing
          (use latest() or metric()).
    """
    try:
        return _ok(lc.filings(company, limit=limit))
    except lc.LedgerError as e:
        return _err(e)


@mcp.tool(name="metric", annotations=_READ_ONLY)
def metric(
    company: CompanyArg,
    name: Annotated[
        str,
        Field(
            description=(
                "Metric name or plain alias — e.g. 'amplification', 'sats per share', "
                "'dividend coverage', 'reserve months', 'cebe', 'claim ratio', 'ntav', "
                "'treasury value', 'btc held', 'sata outstanding', 'cash', or one of the "
                "ledger's own metric keys. Unknown names return every valid one."
            )
        ),
    ],
    as_of: Annotated[
        Optional[str],
        Field(
            description="ISO date (YYYY-MM-DD). Returns the newest filing on or before this date; omit for the newest filing."
        ),
    ] = None,
) -> str:
    """One metric or filing row, at the newest filing or the newest filing
    on or before `as_of`. Never estimated — a row the filing didn't state
    comes back null with a note, never filled in.

    Args:
        company (str): company code, e.g. "asst"
        name (str): metric key or plain alias
        as_of (Optional[str]): ISO date; omit for the newest filing

    Returns:
        str: JSON — {"metric","value","unit","definition","prior","change",
        "as_of","filed","accession","source_url","data_source","btc_price_used"}

    Examples:
        - Use when: "What was Strive's dividend coverage on August 31?"
        - Use when: "How much cash did Strive have in the latest filing?"
        - Don't use when: comparing two filings (use compare()/diff()) or
          re-pricing at a hypothetical BTC price (use stress()).
    """
    try:
        return _ok(lc.metric(company, name, as_of=as_of))
    except lc.LedgerError as e:
        return _err(e)


@mcp.tool(name="compare", annotations=_READ_ONLY)
def compare(
    company: CompanyArg,
    accession_a: Annotated[str, Field(description="First filing's SEC accession number.")],
    accession_b: Annotated[str, Field(description="Second filing's SEC accession number.")],
) -> str:
    """Compare two specific filings, in either order: row-by-row changes,
    reconciliation checks between them, the verdict (accretive / dilutive /
    flat) and funding mix, and the break-even BTC price for that week's
    capital-markets activity.

    Args:
        company (str): company code, e.g. "asst"
        accession_a (str): an SEC accession number, e.g. "0001628280-26-060809"
        accession_b (str): another SEC accession number for the same company

    Returns:
        str: JSON — {"prev","cur","row_changes","reconciliation","verdict",
        "breakeven_btc_price_this_week", ...}

    Examples:
        - Use when: "How did Strive's Aug 24 filing compare to Aug 17?"
        - Don't use when: you want newest-vs-previous (use diff() — no accessions needed).
    """
    try:
        return _ok(lc.compare(company, accession_a, accession_b))
    except lc.LedgerError as e:
        return _err(e)


@mcp.tool(name="diff", annotations=_READ_ONLY)
def diff(company: CompanyArg) -> str:
    """The newest filing against the one immediately before it: row-by-row
    changes, reconciliation checks, the verdict and funding mix, and the
    break-even BTC price for that week's capital-markets activity.

    Args:
        company (str): company code, e.g. "asst"

    Returns:
        str: JSON — same shape as compare().

    Examples:
        - Use when: "Did this week's filing reconcile with last week's?"
        - Use when: "Was the latest filing accretive or dilutive for common?"
    """
    try:
        return _ok(lc.diff(company))
    except lc.LedgerError as e:
        return _err(e)


@mcp.tool(name="stress", annotations=_READ_ONLY)
def stress(
    company: CompanyArg,
    btc_price: Annotated[float, Field(gt=0, description="Hypothetical BTC price in USD.")],
    accession: Annotated[
        Optional[str],
        Field(description="Filing to stress-test (SEC accession number); omit for the newest filing."),
    ] = None,
) -> str:
    """Recompute every metric for one filing at a hypothetical BTC price,
    plus the break-even BTC price (where common's share of the bitcoin goes
    to zero) and the prices where amplification crosses 30% and 100%.

    Args:
        company (str): company code, e.g. "asst"
        btc_price (float): hypothetical BTC price in USD
        accession (Optional[str]): filing to use; omit for the newest filing

    Returns:
        str: JSON — {"metrics_at_price","breakeven_btc_price_usd",
        "amplification_markers", "accession","filed","source_url", ...}

    Examples:
        - Use when: "What is Strive's dividend coverage if Bitcoin falls to $40,000?"
        - Use when: "What's the break-even Bitcoin price for common's bitcoin?"
    """
    try:
        return _ok(lc.stress(company, btc_price, accession=accession))
    except lc.LedgerError as e:
        return _err(e)


@mcp.tool(name="dividends", annotations=_READ_ONLY)
def dividends(company: CompanyArg) -> str:
    """SATA preferred dividend terms as the ledger knows them: par value,
    annual rate, and the resulting annual dividend at the newest filing.
    Says plainly that a day-by-day payment table isn't in the ledger yet.

    Args:
        company (str): company code, e.g. "asst"

    Returns:
        str: JSON — {"sata_par_usd","sata_annual_rate",
        "sata_daily_payment_per_share_usd","annual_dividend_usd","note", ...}

    Example question: "What is Strive's SATA dividend rate and annual payout?"
    """
    try:
        return _ok(lc.dividends(company))
    except lc.LedgerError as e:
        return _err(e)


@mcp.tool(name="definitions", annotations=_READ_ONLY)
def definitions() -> str:
    """Plain-word definitions of every metric this agent computes, plus how
    the accretive/dilutive verdict is decided.

    Returns:
        str: JSON — {"definitions": {name: plain-word definition, ...}}

    Example question: "What does CEBE mean, and how is it different from NTAV?"
    """
    return _ok(lc.definitions())


@mcp.tool(name="source", annotations=_READ_ONLY)
def source(
    company: CompanyArg,
    accession: Annotated[str, Field(description="SEC accession number, e.g. '0001628280-26-061682'.")],
    field: Annotated[
        str, Field(description="A filing row name or alias — e.g. 'cash', 'btc held', 'class_a' — not a derived metric.")
    ],
) -> str:
    """One filing row's prior/current/change, the filing URL, and — when the
    filing text is cached locally — the sentence or table fragment that
    states it, so the answer can be checked word-for-word.

    Args:
        company (str): company code, e.g. "asst"
        accession (str): SEC accession number
        field (str): a filing row name or alias (use metric() for derived metrics)

    Returns:
        str: JSON — {"prior","current","change","source_url","text_cached",
        "text_fragment" (if cached), ...}

    Examples:
        - Use when: "Which filing states Strive's cash on Sept 11, and what exactly does it say?"
        - Don't use when: asking about a computed metric like amplification (use metric()).
    """
    try:
        return _ok(lc.source(company, accession, field))
    except lc.LedgerError as e:
        return _err(e)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="datproof-agent", description="MCP server for DATproof Bitcoin-treasury filing data."
    )
    parser.add_argument("--http", action="store_true", help="Serve streamable HTTP instead of stdio.")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind for --http (default: 127.0.0.1).")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind for --http (default: 8000).")
    args = parser.parse_args()
    if args.http:
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
