"""
app.py — Streamlit frontend for the Blockchain Risk Assessment Tool

Run with:
    streamlit run frontend/app.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
from datetime import datetime, timezone
from api.blockchain_fetcher import fetch_wallet, detect_chain
from api.risk_analyzer import analyze_wallet
from reports.pdf_generator import generate_pdf

# ── Page Config ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Blockchain Risk Analyzer",
    page_icon="🔍",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# ── Custom CSS ────────────────────────────────────────────────────────────────

st.markdown("""
<style>
    .main { max-width: 720px; }
    .risk-badge {
        display: inline-block;
        padding: 6px 18px;
        border-radius: 4px;
        font-weight: bold;
        font-size: 16px;
        color: white;
        margin-bottom: 12px;
    }
    .risk-Critical  { background-color: #C0392B; }
    .risk-High      { background-color: #E67E22; }
    .risk-Medium    { background-color: #D4AC0D; color: #1C2833; }
    .risk-Low       { background-color: #27AE60; }
    .risk-Unknown   { background-color: #95A5A6; }
    .finding-card {
        background: #F8F9FA;
        border-left: 4px solid #2E86C1;
        padding: 12px 16px;
        margin-bottom: 12px;
        border-radius: 0 4px 4px 0;
    }
    .finding-critical { border-left-color: #C0392B; }
    .finding-high     { border-left-color: #E67E22; }
    .finding-medium   { border-left-color: #D4AC0D; }
    .finding-low      { border-left-color: #27AE60; }
</style>
""", unsafe_allow_html=True)

# ── Header ────────────────────────────────────────────────────────────────────

st.title("🔍 Blockchain Risk Analyzer")
st.caption("AI-powered transaction risk assessment mapped to FATF · BSA · OFAC · COSO frameworks")
st.divider()

# ── Input Form ────────────────────────────────────────────────────────────────

with st.form("analyze_form"):
    wallet_input = st.text_input(
        "Wallet Address",
        placeholder="0x... (ETH) or 1... / bc1... (BTC)",
        help="Supports Ethereum and Bitcoin addresses"
    )
    tx_limit = st.slider("Transactions to analyze", min_value=10, max_value=100, value=50, step=10)
    submitted = st.form_submit_button("Run Risk Assessment", type="primary", use_container_width=True)

# ── Analysis Pipeline ─────────────────────────────────────────────────────────

if submitted:
    wallet_input = wallet_input.strip()

    if not wallet_input:
        st.error("Please enter a wallet address.")
        st.stop()

    # Validate address format before hitting APIs
    try:
        chain = detect_chain(wallet_input)
    except ValueError as e:
        st.error(f"Unrecognized address format: {e}")
        st.stop()

    # Step 1: Fetch blockchain data
    with st.status(f"Fetching {chain} transaction history...", expanded=True) as status:
        st.write(f"📡 Querying {'Etherscan' if chain == 'ETH' else 'Blockstream'} API...")
        profile = fetch_wallet(wallet_input, limit=tx_limit)

        if profile.error:
            status.update(label="Data fetch failed", state="error")
            st.error(f"Could not retrieve wallet data: {profile.error}")
            st.stop()

        st.write(f"✅ Retrieved {profile.tx_count} transactions from {profile.unique_counterparties} counterparties")

        # Step 2: Claude risk analysis
        st.write("🤖 Running AI risk analysis via Claude...")
        report = analyze_wallet(profile)

        if report.error:
            status.update(label="Analysis failed", state="error")
            st.error(f"Risk analysis error: {report.error}")
            st.stop()

        # Step 3: Generate PDF
        st.write("📄 Generating audit report PDF...")
        pdf_bytes = generate_pdf(report)

        status.update(label="Analysis complete", state="complete", expanded=False)

    # ── Results Display ───────────────────────────────────────────────────────

    st.divider()

    # Risk rating badge
    rating = report.overall_risk_rating
    score = report.risk_score
    st.markdown(
        f'<span class="risk-badge risk-{rating}">{rating} Risk — {score}/100</span>',
        unsafe_allow_html=True
    )

    # Metadata columns
    col1, col2, col3 = st.columns(3)
    col1.metric("Transactions", report.tx_count_analyzed)
    col2.metric("Counterparties", report.unique_counterparties)
    col3.metric("Findings", len(report.findings))

    # Executive summary
    st.subheader("Executive Summary")
    st.write(report.analyst_note)

    # Risk flags
    if report.flags:
        st.subheader("⚠ Risk Flags")
        for flag in report.flags:
            st.warning(flag, icon="⚠️")

    # Findings
    if report.findings:
        st.subheader("Audit Findings")
        for finding in report.findings:
            css_class = f"finding-{finding.risk_rating.lower()}"
            with st.expander(f"{finding.finding_id} — {finding.title}  [{finding.risk_rating}]", expanded=True):
                st.markdown(f"**Framework:** {finding.framework} — {finding.framework_ref}")
                st.markdown(f"**Description:** {finding.description}")
                st.markdown(f"**Evidence:**")
                st.code(finding.evidence, language=None)
                st.markdown(f"**Recommendation:** {finding.recommendation}")

    st.divider()

    # PDF download
    filename = f"risk_report_{wallet_input[:10]}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.pdf"
    st.download_button(
        label="⬇ Download Audit Report (PDF)",
        data=pdf_bytes,
        file_name=filename,
        mime="application/pdf",
        type="primary",
        use_container_width=True,
    )

    st.caption("Report generated with AI assistance. Intended to supplement, not replace, professional compliance review.")

# ── Empty State ───────────────────────────────────────────────────────────────

else:
    st.info(
        "Enter an Ethereum or Bitcoin wallet address above to generate a compliance risk report. "
        "The tool fetches on-chain transaction data, analyzes it against FATF, BSA, OFAC, and COSO "
        "frameworks using Claude AI, and produces a downloadable audit-ready PDF.",
        icon="ℹ️"
    )

    with st.expander("Sample addresses to try"):
        st.code("0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045", language=None)
        st.caption("Vitalik Buterin's public ETH address — good for testing")
        st.code("34xp4vRoCGJym3xR7yCVPFHoCNxv4Twseo", language=None)
        st.caption("Binance BTC cold wallet — high volume test case")
