# Blockchain Risk Assessment Tool

A Claude-powered blockchain transaction risk analyzer that produces audit-ready PDF reports mapped to compliance frameworks (FATF, BSA, OFAC, COSO).

## What It Does

Input a wallet address (ETH or BTC) or upload a CSV of transactions. The tool fetches on-chain data, runs AI-driven risk analysis via the Claude API, and outputs a professional PDF audit report — the kind of deliverable an IT auditor would hand to a compliance team.

## Risk Frameworks Covered

- **FATF** — Financial Action Task Force travel rule, layering/placement/integration detection
- **BSA** — Bank Secrecy Act suspicious activity indicators
- **OFAC** — Sanctions screening against known addresses
- **COSO** — Control framework mapping for audit findings

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python + FastAPI |
| AI Analysis | Anthropic Claude API |
| Blockchain Data | Etherscan API (ETH), Blockstream API (BTC) |
| Frontend | Streamlit |
| PDF Reports | ReportLab |
| Deployment | Streamlit Cloud |

## Project Structure

```
├── api/             # FastAPI backend + blockchain data fetchers
├── frontend/        # Streamlit UI
├── reports/         # PDF generation logic
├── utils/           # Shared helpers (risk scoring, framework mapping)
├── data/            # Sample wallets and test CSVs
├── .env.example     # Environment variable template
└── requirements.txt
```

## Setup

```bash
# 1. Clone the repo
git clone https://github.com/YOUR_USERNAME/blockchain-risk-assessment.git
cd blockchain-risk-assessment

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# Edit .env with your API keys

# 4. Run the app
streamlit run frontend/app.py
```

## API Keys Needed

- **Anthropic API key** — [console.anthropic.com](https://console.anthropic.com)
- **Etherscan API key** — [etherscan.io/apis](https://etherscan.io/apis) (free tier is sufficient)
- Blockstream (BTC) requires no key

## Built By

Lucas Cashwell — IT Auditor pivoting into crypto-native risk and compliance.  
Built to demonstrate next-generation audit practices applied to blockchain infrastructure.
