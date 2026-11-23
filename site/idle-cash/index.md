# Where should a trading bot keep its idle cash?

The usual places for idle cash, a T-bill or a money market fund, pay 3.9% to 4.1% a year today. Digital credit, bitcoin-backed preferred stock (STRC, SATA and SATS), pays 12.8% to 17.5% a year, with a dividend every business day. The price moves, so the record below shows how past holds turned out.

Data for 22 Nov 2026 · prices at the 20 Nov 2026 close · SATA rate last published 13 Nov 2026. Page: https://lucascashwell3-ai.github.io/datproof/idle-cash/

## What does idle cash pay today?

| Where | Pays a year | Date | On $10,000 a year | Price | Flags |
|---|---|---|---|---|---|
| STRC (Strategy · pays every business day) | 12.8% | 20 Nov 2026 | $1,282 | $93.60 (20 Nov 2026) | Price moves daily · Issuer sets the rate |
| SATA (Strive · pays every business day) | 15.3% | rate last published 13 Nov 2026 | $1,529 | $85.00 (20 Nov 2026) | Price moves daily · Issuer sets the rate |
| SATS (Strive · pays every business day) | 17.5% | 20 Nov 2026 | $1,749 | $85.76 (20 Nov 2026) | Price moves daily · Issuer sets the rate · Short record |
| 4-week T-bill (US Treasury) | 4.1% | 20 Nov 2026 | $411 | no share price | Nothing flagged |
| Money market fund (Vanguard VMFXX) | 3.9% | 22 Nov 2026 | $395 | no share price | Not bank insured |
| USDC lending (Aave v3, Ethereum) | 2.5% | 22 Nov 2026 | $251 | no share price | Smart-contract risk |

Yield is the stated rate at the latest close. Income is simple interest, before tax and fees, and ignores price changes.

## How did past holds turn out?

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

## How far can the price drop?

The largest fall from a high close to a later close, from the feed's daily closes:

- STRC fell 25.5%, from $100.07 on 12 Jan 2026 to $74.57 on 26 Jun 2026, its largest fall in 251 daily closes since 21 Nov 2025. It closed at $93.60 on 20 Nov 2026.
- SATA fell 17.9%, from $100.53 on 16 Jan 2026 to $82.50 on 5 Feb 2026, its largest fall in 251 daily closes since 21 Nov 2025. It closed at $85.00 on 20 Nov 2026.
- SATS fell 11.5%, from $96.92 on 13 Nov 2026 to $85.76 on 20 Nov 2026, in a short record: 26 daily closes since 16 Oct 2026. It closed at $85.76 on 20 Nov 2026.

STRC: 31% of 3-month holds lost money, 68% beat a T-bill; SATA: 8% of 3-month holds lost money, 87% beat a T-bill.

## Will it raise my bot's Sharpe ratio?

DATproof does not measure that. It adds income on the cash that is not in a trade: a $10,000 account that sits 60% in cash earns about $912 a year on that $6,000 at today's average yield of STRC, SATA and SATS, before tax. It also adds the price swings above.

## Which cash does it fit?

Cash your trading agent won't need for a few months. STRC and SATA have variable rates their issuers say they adjust to keep the price near $100. SATS has a fixed rate and no stated aim to keep the price near $100, so its price is free to move. Not for money needed tomorrow at an exact dollar amount: that belongs in a T-bill or money market fund.

## Connect your agent

Running your agent on Robinhood or Alpaca? Add DATproof alongside your broker connection. Your agent reads DATproof; trades still go through your own broker, with your approval.

    claude mcp add datproof -- uvx --from git+https://github.com/lucascashwell3-ai/datproof datproof-mcp

- JSON feed: https://lucascashwell3-ai.github.io/datproof/v1/instruments.json
- For AI readers: https://lucascashwell3-ai.github.io/datproof/llms.txt

Every number is sourced and dated. Prices move and issuers set the rates. This is data, not personal advice.
