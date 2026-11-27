# DATproof

**[Live site →](https://lucascashwell3-ai.github.io/datproof/)**

An adoption accelerator for digital asset treasuries — an information hub for corporate
Bitcoin purchase data. Every disclosed BTC purchase since 2020 on one activity grid, each
square linked to the filing behind it, with the funding beside the buys: at-the-market
share sales and the digital credit instruments (STRC, SATA) that raise the cash.

## How it works

- **The data** — `data/moves/*.csv`: one row per disclosed move (BTC buy or ATM sale) for
  Strategy, Strive, and Metaplanet, each with date, amounts, and its `source_url`. What
  can't be sourced from a filing isn't in the data.
- **The pullers** — `scripts/pull_mstr.py`, `pull_asst.py`, `pull_metaplanet.py` read the
  companies' disclosures; `scripts/build_grid_site.py` renders `site/grid/index.html` (served at `/grid/`) from the
  CSVs plus a keyless BTC ticker (`scripts/fetch_ticker.py`).
- **The Action** — `.github/workflows/grid.yml` re-pulls, rebuilds, and redeploys the site
  every day.
- **Dry runs** — `gh workflow run grid.yml --ref <branch> -f dry_run=true` pulls, builds, and
  runs the checks below with nothing committed or deployed; any run on a branch other than
  `main` does the same automatically, so a branch can never push data to `main`.
- **Source status** — `data/run-status.json`, written and committed each run, records
  ok/failed per data source, the newest filing date found for each, and whether the data has
  gone stale — so a source that fails quietly (old behavior: keep last data, stay green,
  nobody notices) now shows up instead of hiding.

## Where can idle cash sit?

A free daily data feed for anyone with idle cash and the AI they ask. It lists the Bitcoin
treasury preferred stocks (STRC, SATA, SATS, STRF, STRK, STRD) beside what idle cash earns
in savings, CDs, a money market fund, T-bills and a municipal bond fund, each with its
yield, its worst past-year price fall, its payment record and risk flags. Every number names
its source and date; a number that could not be fetched is empty, with the reason.

- **Files** (rebuilt each day): `https://lucascashwell3-ai.github.io/datproof/v1/` +
  `instruments.json`, `instrument/<TICKER>.json`, `changes.json`, `scenarios.json`,
  `method.json` (every formula and flag in plain words), `status.json`, and the dated
  `days/<date>.json`.
- **Page** (rewritten each day from the files, figures as plain text so readers that run no
  script still get them): the home page, `https://lucascashwell3-ai.github.io/datproof/`, with a Markdown copy at `index.md`.
  `python -m datproof_feed.pages` rebuilds it.
- **By price paid**: `by_buy_price` in each instrument splits the 30, 90 and 180-day holds by the
  close paid (under $90, $90 to $95, $95 to $100, $100 and over): buys, losses, average and worst
  result, and how many separate drops the buys came from, for every issue, with whether its issuer
  states it adjusts the rate to keep the price near $100.
- **Sharpe**: `sharpe` in each instrument: past-year Sharpe ratio, total return and yearly swings from
  daily total returns, plus a worked example of a bot moving all of its idle cash in.
- **Crash test**: `backing` in each Strategy and Strive preferred: (bitcoin held × bitcoin price + cash)
  ÷ (debt + every preferred ahead in line + the issue itself), the bitcoin price where that falls to
  1.0×, and years of the yearly bill covered by cash set aside. `python -m datproof_feed.backing`
  fetches the daily inputs into `data/backing.json`; filing figures live in `data/backing_static.json`.
- **Compare** (the plug-in's tool) takes an amount in dollars, how long the cash can sit (1 month,
  3 months, 6 months or 1 year) and where it sits today (checking, savings, high-yield savings,
  12-month CD, money market fund, T-bill or broker cash). It returns the same rows for STRC, SATA
  and SATS in fixed order: dividends over that time, what the cash earns now at a named, sourced
  rate, the difference, how past holds of that length turned out (or the date results begin),
  whole shares at the last close and brokers' pages for each ticker. The page's "Your situation"
  form does the same arithmetic. `compare.situation` holds it for both.
- **Comparison rates and where to buy**: `python -m datproof_feed.rates` refreshes
  `data/comparison_rates.json` (each rate dated and sourced, last good figure kept on a failure,
  0-15% and no 2-point one-day move); `python -m datproof_feed.brokers` checks the broker links in
  `data/where_to_buy.json` daily. Both are joined into `instruments.json` at publish time.
- **Scenarios** show what $10,000 did over the past 30, 90, 180 and 365 days in each
  preferred stock (dividends paid, price change, lowest point and its date), beside the T-bill
  and money market fund at today's rate, plus three named situations. Past results do not
  predict future results.

### Use it

```bash
# 1. Run the tool server for any MCP client (or, from a clone: python3 -m datproof_feed.server)
uvx --from git+https://github.com/lucascashwell3-ai/datproof datproof-mcp

# 2. Optional: add the Claude Code skill that walks through the questions
cp -r skills/park-idle-cash ~/.claude/skills/
```

It never holds or moves money, places no orders, and is not advice: facts and arithmetic
only.

## Visitor count (off)

Set `site/config.json` to `{"counter": {"provider": "goatcounter", "code": "<your site code>"}}` (or `"cloudflare"` with the 32-character token) and the next daily build adds that one cookie-free counter script to the home page.
Leave `provider` empty and nothing is added; any other provider, or a code that is not a plain site code or token, stops the page build.

## Run it locally

```bash
python3 scripts/build_grid_site.py
python3 -m http.server 8471 --directory site
```

## Repo notes

- `archive/2026-07-rating-agency/` — DATproof's first concept (A–F evidence grades),
  retired 2026-07-30 and kept for the record.
- `.github/workflows/daily-brief.yml` — legacy manual-dispatch fallback from that concept;
  the cron was removed 2026-08-22.
- Tests live in `tests/`.

Built by [Lucas Cashwell](https://github.com/lucascashwell3-ai) · part of the `-proof`
family (Skillproof · Modelproof).
