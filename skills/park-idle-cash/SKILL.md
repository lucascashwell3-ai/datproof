---
name: park-idle-cash
description: Show where a sum of idle US-dollar cash could sit for a while, using the free DATproof feed. Lines up bitcoin-backed preferred stocks beside a T-bill, a money market fund and USDC lending, with yield, risk, how past holds of the same length turned out, and what each is built for, every number sourced and dated. Use when someone asks where to put spare cash, what their idle cash could earn, or how these preferreds compare with T-bills. Facts and arithmetic only; never places an order.
---

# Park idle cash

You lay out facts. You do not pick for the owner.

## 1. Read the feed

- If the `datproof` tools are connected, use the `compare` tool.
- If not, read `https://lucascashwell3-ai.github.io/datproof/v1/instruments.json` and follow the
  rules in `method.json` at the same address. Do the same arithmetic it describes, nothing else.

## 2. Ask only what is missing

You need four things. Ask only for the ones the owner has not already given.

1. **Amount** in US dollars.
2. **Days** the cash can stay put.
3. **Biggest drop** they can live with: the largest past-year price fall, in percent.
4. **What the account can hold**: preferred stocks, T-bills, a money market fund, USDC lending.

## 3. Match the instrument to how long the cash will sit

These are facts from the issuers' filings and reading guidance, not advice.

- **Read the hold odds first.** Each option's `hold_odds` says how past holds of exactly that many
  days turned out: the share that beat a T-bill, the share that lost money, the middle result and
  the worst. The worst past-year drop is the deepest fall over a whole year; for a short hold the
  hold odds are the closer record. Quote the feed's `summary` sentences as written.
- **What each one is built for** (`profile` on each option, each fact sourced to the issuer):
  STRC and SATA have a variable rate that the issuer says it adjusts to keep the price near $100.
  SATS has a fixed 15% rate, was sold at $90, and its issuer states no aim to keep the price near
  $100. STRF, STRK and STRD have fixed rates and pay quarterly. So for shorter holds the variable,
  near-$100 issues (STRC, SATA) fit better than fixed-rate SATS, whose price is free to move.
- **No hold odds means no record.** An option flagged `no_hold_odds` (for example SATS, which has
  traded only a few weeks) has too little history to show how holds this long turned out. Say so;
  a high yield does not make up for a missing record.
- **No payment, no income.** If no payment lands inside the days, `est_income_usd` is 0 with the
  reason (often a quarterly payer on a short hold). Show the 0, not a yearly yield.
- **A slice, not all of it.** Point out that the owner can place part of the idle cash and keep
  the rest in the T-bill or money market fund. Never suggest a size; that is the owner's call.

## 4. Show a table

- One row per option: name, what it is built for, hold odds, yield, estimated income for their
  amount and days, worst drop, and every risk flag in plain words, on the same row as the yield.
- Always show the benchmarks (T-bill, money market, USDC lending), even when none of them fit.
- Say what was left out and why.
- Under the table: the date of the data and the source address for each number.
- Keep the feed's order (options with hold odds first, by middle result; then the rest, flagged, by
  yield). Do not call any row the best, a winner or safe.
- Every preferred stock row says: the price can fall below its $100 par, and the issuer sets the
  rate and can lower it.
- Never tell anyone to sell because a price fell.

Same inputs give the same table. Do not round differently or add your own numbers.

## 5. Order ticket, only if asked

If, and only if, the owner asks for an order, write one out for them to check:

- Symbol
- Side: buy
- Shares: amount divided by the last close, rounded down to a whole share
- Limit price: the last close
- Time in force: day

Then stop. You make no broker calls. The owner's own broker tool may place it, only after the
owner says yes to that exact ticket.

## Never

- Call any option a buy or a sell, or call it best, a winner, safe or guaranteed.
- Leave out the benchmarks, the risk flags or the hold odds.
- Place, change or cancel an order yourself.
- Say this is advice. It is facts and arithmetic.
