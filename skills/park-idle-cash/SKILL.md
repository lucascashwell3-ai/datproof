---
name: park-idle-cash
description: Show where a sum of idle US-dollar cash could sit for a while, using the free DATproof feed. Lines up bitcoin-backed preferred stocks beside a T-bill, a money market fund and USDC lending, with yield and risk side by side and every number sourced and dated. Use when someone asks where to put spare cash, what their idle cash could earn, or how these preferreds compare with T-bills. Facts and arithmetic only; never places an order.
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

## 3. Show a table

- One row per option: name, yield, estimated income for their amount and days, worst drop, and
  every risk flag in plain words, on the same row as the yield.
- Always show the benchmarks (T-bill, money market, USDC lending), even when none of them fit.
- Say what was left out and why.
- Under the table: the date of the data and the source address for each number.
- Keep the feed's order (highest yield first). Do not call any row the best, a winner or safe.
- Every preferred stock row says: the price can fall below its $100 par, and the issuer sets the
  rate and can lower it.
- Never tell anyone to sell because a price fell.

Same inputs give the same table. Do not round differently or add your own numbers.

## 4. Order ticket, only if asked

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
- Leave out the benchmarks or the risk flags.
- Place, change or cancel an order yourself.
- Say this is advice. It is facts and arithmetic.
