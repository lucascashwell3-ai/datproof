# DATproof: earn more on your trading agent's idle cash

Cash your trading agent won't need for a few months can earn daily dividends from digital credit. DATproof gives your agent the live numbers and the odds.

Data for 22 Nov 2026 · prices at the 20 Nov 2026 close · SATA rate last published 13 Nov 2026. Page with charts: https://lucascashwell3-ai.github.io/datproof/next/

## Today's numbers

| Where | Pays a year | Date | On $10,000 a year | Price | Flags |
|---|---|---|---|---|---|
| STRC (Strategy · pays every business day) | 12.8% | 20 Nov 2026 | $1,282 | $93.60 (20 Nov 2026) | Price moves daily · Issuer sets the rate |
| SATA (Strive · pays every business day) | 15.3% | rate last published 13 Nov 2026 | $1,529 | $85.00 (20 Nov 2026) | Price moves daily · Issuer sets the rate · A figure is more than 4 days old |
| SATS (Strive · pays every business day) | 17.5% | 20 Nov 2026 | $1,749 | $85.76 (20 Nov 2026) | Price moves daily · Issuer sets the rate · Short record |
| 4-week T-bill (US Treasury) | 4.1% | 20 Nov 2026 | $411 | no share price | Nothing flagged |
| Money market fund (Vanguard VMFXX) | 3.9% | 22 Nov 2026 | $395 | no share price | Not bank insured |
| USDC lending (Aave v3, Ethereum) | 2.5% | 22 Nov 2026 | $251 | no share price | Smart-contract risk |

Yield is the stated rate at the latest close. Income is simple interest, before tax and fees, and ignores price changes.

## The odds for the time your cash has

| Stock | Held | Beat a T-bill | Lost money | Typical result | Worst |
|---|---|---|---|---|---|
| STRC | 1 week | 61% | 25% | +0.3% | −14.6% |
| STRC | 1 month | 76% | 19% | +1.1% | −23.8% |
| STRC | 3 months | 68% | 31% | +3.2% | −22.5% |
| SATA | 1 week | 65% | 31% | +0.4% | −14.3% |
| SATA | 1 month | 70% | 26% | +1.5% | −15.0% |
| SATA | 3 months | 87% | 8% | +4.9% | −11.5% |

Every start day in the past year (closes from 21 Nov 2025 to 22 Nov 2026): buy, hold, collect the dividends, sell. Scored against a 4-week T-bill held for the same stretch (4.11% a year today).

SATS: not enough history: 0 past holds of 90 days fit in 26 trading days of closes; 60 are needed.

## Connect your agent

Running your agent on Robinhood or Alpaca? Add DATproof alongside your broker connection. Your agent reads DATproof; trades still go through your own broker, with your approval.

    claude mcp add datproof -- uvx --from git+https://github.com/lucascashwell3-ai/datproof datproof-mcp

- Where should a trading bot keep its idle cash? https://lucascashwell3-ai.github.io/datproof/idle-cash/
- JSON feed: https://lucascashwell3-ai.github.io/datproof/v1/instruments.json
- For AI readers: https://lucascashwell3-ai.github.io/datproof/llms.txt

Every number is sourced and dated. Prices move and issuers set the rates. This is data, not personal advice.
