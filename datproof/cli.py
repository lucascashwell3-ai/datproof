"""CLI entry point.

Usage:
    python -m datproof brief [--out DIR] [--btc-price N] [--market-cap TICKER=USD ...] [--no-ai]
    python -m datproof verify ADDRESS [ADDRESS ...]
    python -m datproof landscape [--btc-price N]
"""

import argparse
import sys
from pathlib import Path

from . import brief as brief_mod
from .metrics import compute_metrics
from .onchain import get_address_balance, get_spot_price
from .registry import load_registry
from .risk import evaluate


def _apply_market_caps(registry, pairs: list[str]) -> None:
    for pair in pairs:
        ticker, _, value = pair.partition("=")
        company = next((c for c in registry.companies if c.ticker == ticker), None)
        if company is None:
            sys.exit(f"Unknown ticker: {ticker}")
        company.market_cap_usd = float(value)


def cmd_brief(args) -> None:
    registry = load_registry()
    _apply_market_caps(registry, args.market_cap or [])
    spot = get_spot_price(override=args.btc_price,
                          fallback_usd=registry.btc_spot_snapshot_usd,
                          fallback_as_of=registry.btc_spot_snapshot_as_of)
    metrics = compute_metrics(registry, spot.usd)
    findings = evaluate(metrics)

    commentary = None if args.no_ai else brief_mod.generate_commentary(metrics, findings, spot)
    brief_md = brief_mod.render_brief(metrics, findings, spot, commentary=commentary)
    post_md = brief_mod.render_linkedin_draft(metrics, findings, spot)

    if args.out:
        out_dir = Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)
        from datetime import datetime
        stamp = datetime.utcnow().strftime("%Y-%m-%d")
        (out_dir / f"brief-{stamp}.md").write_text(brief_md)
        (out_dir / f"post-draft-{stamp}.md").write_text(post_md)
        print(f"Wrote brief-{stamp}.md and post-draft-{stamp}.md to {out_dir}/")
    else:
        print(brief_md)


def cmd_verify(args) -> None:
    for address in args.addresses:
        result = get_address_balance(address)
        if result.btc is not None:
            print(f"{address}: {result.btc:,.8f} BTC ({result.source})")
        else:
            print(f"{address}: unavailable — {result.error}")


def cmd_landscape(args) -> None:
    registry = load_registry()
    spot = get_spot_price(override=args.btc_price,
                          fallback_usd=registry.btc_spot_snapshot_usd,
                          fallback_as_of=registry.btc_spot_snapshot_as_of)
    metrics = compute_metrics(registry, spot.usd)
    print(f"BTC ${spot.usd:,.0f} ({spot.source}) · "
          f"{metrics.total_btc:,.0f} BTC tracked · "
          f"verifiable {metrics.verifiable_pct:.1f}% · "
          f"top-1 concentration {metrics.concentration_top1_pct:.1f}%")
    for m in metrics.companies:
        pnl = f"{m.unrealized_pnl_pct:+.1f}%" if m.unrealized_pnl_pct is not None else "  n/a"
        print(f"  {m.company.name:<38} {m.company.btc_holdings:>12,.0f} BTC  {pnl}")


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="datproof",
                                     description="DAT treasury verification & risk intelligence")
    sub = parser.add_subparsers(dest="command", required=True)

    p_brief = sub.add_parser("brief", help="Generate the daily brief + LinkedIn draft")
    p_brief.add_argument("--out", help="Directory to write markdown files")
    p_brief.add_argument("--btc-price", type=float, help="Override BTC spot price")
    p_brief.add_argument("--market-cap", action="append", metavar="TICKER=USD",
                         help="Supply a market cap to enable mNAV (repeatable)")
    p_brief.add_argument("--no-ai", action="store_true", help="Skip Claude commentary")
    p_brief.set_defaults(func=cmd_brief)

    p_verify = sub.add_parser("verify", help="Check on-chain balances for addresses")
    p_verify.add_argument("addresses", nargs="+")
    p_verify.set_defaults(func=cmd_verify)

    p_land = sub.add_parser("landscape", help="One-screen summary of the DAT landscape")
    p_land.add_argument("--btc-price", type=float, help="Override BTC spot price")
    p_land.set_defaults(func=cmd_landscape)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
