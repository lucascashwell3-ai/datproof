# DATproof: earn more on your trading agent's idle cash

Cash your trading agent won't need for a few months can earn daily dividends from digital credit. DATproof gives your agent the live numbers and the odds.

Data for 26 Nov 2026 · prices at the 25 Nov 2026 close. Page with charts: https://lucascashwell3-ai.github.io/datproof/next/

## Income every business day

| Where | Pays a year | Date | On $10,000 a year | Price | After inflation |
|---|---|---|---|---|---|
| STRC (Strategy · pays every business day) | 12.2% | 25 Nov 2026 | $1,224 | $98.04 (25 Nov 2026) | +8.5% |
| SATA (Strive · pays every business day) | 14.3% | rate as of 13 Nov 2026 | $1,435 | $90.62 (25 Nov 2026) | +10.6% |
| SATS (Strive · pays every business day) | 16.9% | 25 Nov 2026 | $1,695 | $88.50 (25 Nov 2026) | +13.2% |
| 4-week T-bill (US Treasury) | 4.2% | 25 Nov 2026 | $419 | no share price | +0.5% |
| Money market fund (Vanguard VMFXX) | 3.9% | 26 Nov 2026 | $395 | no share price | +0.2% |
| USDC lending (Aave v3, Ethereum) | 3.0% | 26 Nov 2026 | $299 | no share price | −0.7% |

Yield is the stated rate at the latest close. Income is simple interest, before tax and fees, and ignores price changes. After inflation is the yield minus US CPI inflation, 3.7% for the 12 months to September 2026.

## Under $100, more yield and room to climb

Under $100 you earn more on what you pay, and the issuers of STRC and SATA say they adjust the rate to keep the price near $100 (STRC filing: https://www.sec.gov/Archives/edgar/data/1050446/000119312525165531/d852456d424b5.htm, SATA filing: https://www.sec.gov/Archives/edgar/data/1920406/000114036126002238/ny20063534x5_424b5.htm).

- STRC: $98.04 at the 25 Nov 2026 close, $1.96 under $100; pays 12.2% at this price, stated rate 12.0%.
- SATA: $90.62 at the 25 Nov 2026 close, $9.38 under $100; pays 14.3% at this price, stated rate 13.0% (rate as of 13 Nov 2026).

| Bought at | STRC | SATA |
|---|---|---|
| under $90 | +18.4%: 31 buys, 0 lost, worst +12.5% | +18.4%: 9 buys, 0 lost, worst +15.0% |
| $90 to $95 | +8.7%: 13 buys, 0 lost, worst +5.9% | +8.4%: 48 buys, 0 lost, worst +3.0% |
| $95 to $100 | +0.2%: 113 buys, 38 lost, worst −22.5% | +3.0%: 114 buys, 12 lost, worst −11.5% |
| $100 and over | −2.8%: 32 buys, 20 lost, worst −13.5% | −0.2%: 18 buys, 6 lost, worst −11.8% |

90-day holds bought from 25 Nov 2025 to 27 Aug 2026, dividends included; the figure is the average result. Largest fall from a high close in the past year: STRC 25.5%, from $100.07 on 12 Jan 2026 to $74.57 on 26 Jun 2026; SATA 17.9%, from $100.53 on 16 Jan 2026 to $82.50 on 5 Feb 2026. The under-$90 buys came from 1 separate drop for STRC and 2 separate drops for SATA.

## The odds for the time your cash has

| Stock | Held | Beat a T-bill | Lost money | Typical result | Worst |
|---|---|---|---|---|---|
| STRC | 1 week | 61% | 26% | +0.3% | −14.6% |
| STRC | 1 month | 75% | 20% | +1.1% | −23.8% |
| STRC | 3 months | 68% | 31% | +3.2% | −22.5% |
| SATA | 1 week | 64% | 32% | +0.4% | −14.3% |
| SATA | 1 month | 69% | 27% | +1.5% | −15.0% |
| SATA | 3 months | 85% | 10% | +4.7% | −11.8% |

Every start day in the past year (closes from 25 Nov 2025 to 26 Nov 2026): buy, hold, collect the dividends, sell. Scored against a 4-week T-bill held for the same stretch (4.19% a year today).

SATS is too new to score.

## What does it add to an account?

A $10,000 account that sits 60% in cash earns about $871 a year on that $6,000 at today's average yield of STRC, SATA and SATS, before tax.

## Questions

### Where should a trading bot keep its idle cash?

The usual places for idle cash, a T-bill or a money market fund, pay 3.9% to 4.2% a year today. Digital credit, bitcoin-backed preferred stock (STRC, SATA and SATS), pays 12.2% to 16.9% a year, with a dividend every business day.

### How did past holds turn out?

Of 3-month holds started each day over the past year, STRC lost money 31% of the time and beat a 4-week T-bill 68%; SATA lost money 10% of the time and beat a 4-week T-bill 85%.

### Which cash does it fit?

Cash your trading agent won't need for a few months. Money needed tomorrow at an exact dollar amount belongs in a T-bill or money market fund. SATS has a fixed rate and no stated aim to keep the price near $100, so its price is free to move.

## Connect your agent

Running your agent on Robinhood or Alpaca? Add DATproof alongside your broker connection. Your agent reads DATproof; trades still go through your own broker, with your approval.

    claude mcp add datproof -- uvx --from git+https://github.com/lucascashwell3-ai/datproof datproof-mcp

- JSON feed: https://lucascashwell3-ai.github.io/datproof/v1/instruments.json
- For AI readers: https://lucascashwell3-ai.github.io/datproof/llms.txt

Every number is sourced and dated. Prices move and issuers set the rates. This is data, not personal advice.
