"""DATproof — Streamlit dashboard.

Run: streamlit run frontend/datproof_app.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st

from datproof.brief import render_linkedin_draft
from datproof.metrics import compute_metrics
from datproof.onchain import get_spot_price
from datproof.registry import load_registry
from datproof.risk import evaluate

st.set_page_config(page_title="DATproof — DAT Risk Intelligence", page_icon="🛡️", layout="wide")

st.title("🛡️ DATproof")
st.caption(
    "On-chain verification & risk intelligence for Digital Asset Treasury companies. "
    "Trust, but verify."
)

registry = load_registry()

with st.sidebar:
    st.header("Analysis inputs")
    price_override = st.number_input(
        "BTC price override (0 = live/cached)", min_value=0.0, value=0.0, step=1000.0
    )
    st.markdown("**Market caps (optional, enables mNAV)**")
    market_caps: dict[str, float] = {}
    for company in registry.companies:
        if company.ticker:
            value = st.number_input(
                f"{company.ticker} market cap ($B)", min_value=0.0, value=0.0,
                step=1.0, key=f"mc_{company.id}",
            )
            if value > 0:
                market_caps[company.ticker] = value * 1e9
    st.caption(
        "DATproof never guesses market caps — supply them here to compute "
        "mNAV (market cap ÷ BTC net asset value)."
    )

for company in registry.companies:
    if company.ticker in market_caps:
        company.market_cap_usd = market_caps[company.ticker]

spot = get_spot_price(
    override=price_override or None,
    fallback_usd=registry.btc_spot_snapshot_usd,
    fallback_as_of=registry.btc_spot_snapshot_as_of,
)
metrics = compute_metrics(registry, spot.usd)
findings = evaluate(metrics)

col1, col2, col3, col4 = st.columns(4)
col1.metric("BTC spot", f"${spot.usd:,.0f}", help=f"Source: {spot.source} ({spot.as_of})")
col2.metric("Tracked corporate BTC", f"{metrics.total_btc:,.0f}")
col3.metric("Verifiable on-chain", f"{metrics.verifiable_pct:.1f}%")
col4.metric("Top-1 concentration", f"{metrics.concentration_top1_pct:.1f}%")

st.subheader("Holdings")
rows = []
for m in metrics.companies:
    c = m.company
    rows.append({
        "Company": c.name,
        "Ticker": c.ticker or "private",
        "BTC": c.btc_holdings,
        "Value ($B)": round(m.holdings_value_usd / 1e9, 2),
        "Share %": round(m.share_of_registry_pct, 1),
        "vs avg cost %": round(m.unrealized_pnl_pct, 1) if m.unrealized_pnl_pct is not None else None,
        "mNAV": round(m.mnav, 2) if m.mnav is not None else None,
        "Verifiable": "✅" if m.verifiable else "❌",
        "As of": c.as_of,
    })
st.dataframe(rows, use_container_width=True, hide_index=True)

st.subheader(f"Risk findings ({len(findings)})")
severity_icon = {"critical": "🟣", "high": "🔴", "medium": "🟠", "low": "🟡"}
for f in findings:
    with st.expander(f"{severity_icon[f.severity]} [{f.severity.upper()}] {f.title}"):
        st.markdown(f"**Assertion:** {f.assertion}")
        st.markdown(f"**Frameworks:** {', '.join(f.frameworks)}")
        st.write(f.detail)

st.subheader("Today's LinkedIn draft")
st.code(render_linkedin_draft(metrics, findings, spot), language="markdown")

st.divider()
st.caption(
    "Holdings figures are company disclosures as of their stated dates. Not investment advice. "
    "Built by Lucas Cashwell — IT auditor applying audit-grade rigor to digital asset treasuries."
)
