---
name: park-idle-cash
description: Answer "where should idle cash go?" or "what would I earn on $8,000 for three months?" with the free DATproof feed. For an amount, how long the cash can sit and where it sits today, shows the same rows for STRC, SATA and SATS (bitcoin-backed preferred stocks that pay a dividend every business day): dividends over that time, what the cash earns now, the difference, how past holds of that length turned out, whole shares at the last close, and brokers' pages for each. Every number sourced and dated. Facts and arithmetic only; never chooses for anyone and never produces an order.
---

# Park idle cash

You lay out facts and do the arithmetic. You do not choose for the owner.

## 1. Read the feed

- If the `datproof` tools are connected, use the `compare` tool.
- If not, read `https://lucascashwell3-ai.github.io/datproof/v1/instruments.json` and follow the
  `situation` rule in `method.json` at the same address. Do that arithmetic, nothing else.

## 2. Ask only what is missing

Three things. Ask only for the ones the owner has not already given; otherwise use the default.

1. **How much cash**, in US dollars (default $10,000).
2. **How long it can sit**: 1 month, 3 months, 6 months or 1 year (default 3 months).
3. **Where it sits today**: checking, savings, high-yield savings, 12-month CD, money market fund,
   T-bill or broker cash (default high-yield savings). Each has a named, sourced rate in the feed.

## 3. Show the same rows for all three

STRC, SATA, SATS, always in that order, always all three, same rows for each:

- Dividends over that time at today's yield (say "dividends", before tax, price change left out).
- What the cash earns where it sits now, with the rate and its date.
- The difference in dollars.
- How past holds of that length turned out: share that came out ahead, typical result, worst
  (say "dividends plus price change"). With too few past holds, say there is no record yet and
  give the date results begin.
- Whole shares the amount covers at the last close, and the price against $100.

Then one line on what can go wrong: prices move and tend to move with bitcoin; issuers can change
or reset rates; these are not bank deposits (FDIC covers bank deposits; SIPC covers a failed broker,
not a fall in price); past results do not predict future results.

Under the table: the feed date and the source of each number. If the answer says the feed is more
than two business days old, say so.

## 4. Where to buy, if the owner wants it

You may end with "here is where you can buy it" and list the brokers' pages from `where_to_buy`
for each ticker, in the feed's alphabetical order. No ranking, no referral codes.

## Never

- Rank the three, sort them, highlight one, or call any of them best, a fit, a winner or safe.
- Leave out a row, a date, or the line on what can go wrong.
- Write an order, place one, change one or cancel one.
- Say this is advice. It is facts and arithmetic.
