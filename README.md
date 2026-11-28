# DATproof

**Where idle cash can earn more than a savings account, with the record and the risks.**

A free daily page and data feed for anyone with idle cash at a US broker or bank, and the AI
they ask. It shows three bitcoin-backed preferred stocks that pay a dividend every business day
(STRC, SATA and SATS) beside savings, CDs, a money market fund and T-bills: today's yields, how
past holds turned out, a bitcoin crash test and what can go wrong. Every number carries its
source and date. It informs and does arithmetic; it never picks one, holds no money and places
no orders. Not advice.

- **Page:** https://datproof.com/ (Markdown copy at `index.md`, a guide for AI readers at `llms.txt`)
- **Feed:** https://datproof.com/v1/instruments.json
- **Plug-in for your AI agent, one command:**

```bash
claude mcp add datproof -- uvx --from git+https://github.com/lucascashwell3-ai/datproof@bdab0e3250013783a6c5d9372dfe5ba0fb70ac80 datproof-mcp
```

- **Or use it without installing:** the hosted copy at `https://mcp.datproof.com/mcp` (streamable HTTP).
  No key and no sign-in; the same seven read-only tools as the installed plug-in.

## The feed and the page

The feed lists the bitcoin treasury preferred stocks (STRC, SATA, SATS, STRF, STRK, STRD) beside what idle cash earns
in savings, CDs, a money market fund, T-bills and a municipal bond fund, each with its
yield, its worst past-year price fall, its payment record and risk flags. Every number names
its source and date; a number that could not be fetched is empty, with the reason.

- **Files** (rebuilt each day): `https://datproof.com/v1/` +
  `instruments.json`, `instrument/<TICKER>.json`, `changes.json`, `scenarios.json`,
  `method.json` (every formula and flag in plain words), `status.json`, and the dated
  `days/<date>.json`.
- **Page** (rewritten each day from the files, figures as plain text so readers that run no
  script still get them): the home page, `https://datproof.com/`, with a Markdown copy at `index.md`.
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
- **Check** (the plug-in's tool for the step before buying) takes one ticker, an optional amount and
  the owner's own limits: lowest yield at today's price, highest price, lowest backing, biggest
  past-year fall, largest share of an average day's trading, the oldest any figure may be in
  business days, and a current dividend. For each it returns the fact with its date and source and a
  result: pass, fail, no limit set, or cannot tell (the fact is missing, undated or older than
  allowed). The age limit applies to every figure behind a check, not only the feed's date: any
  figure older than it reads cannot tell, and figures from company filings (debt, for instance) can
  be weeks old. A current dividend fails on a missed payment or when the last payment is overdue for
  the issue's own pay schedule, and reads cannot tell when the schedule or a date is unknown. `limits_met`
  is true only when every limit sent passed. With an amount, it adds the last close, the whole shares
  that amount buys and the cash left. It compares facts with the owner's limits; it is not a
  recommendation and places no order.
- **Plug-in tools** (seven, all read-only): `compare`, `instrument`, `instruments`, `changes`,
  `scenarios`, `method`, `check`.
- **Comparison rates and where to buy**: `python -m datproof_feed.rates` refreshes
  `data/comparison_rates.json` (each rate dated and sourced, last good figure kept on a failure,
  0-15% and no 2-point one-day move); `python -m datproof_feed.brokers` checks the broker links in
  `data/where_to_buy.json` daily. Both are joined into `instruments.json` at publish time.
- **Scenarios** show what $10,000 did over the past 30, 90, 180 and 365 days in each
  preferred stock (dividends paid, price change, lowest point and its date), beside the T-bill
  and money market fund at today's rate, plus three named situations. Past results do not
  predict future results.

### Use it with any MCP client

```bash
# 1. Run the tool server for any MCP client (or, from a clone: python3 -m datproof_feed.server)
uvx --from git+https://github.com/lucascashwell3-ai/datproof@bdab0e3250013783a6c5d9372dfe5ba0fb70ac80 datproof-mcp

# 2. Optional: add the Claude Code skill that walks through the questions
cp -r skills/park-idle-cash ~/.claude/skills/
```

It never holds or moves money, places no orders, and is not advice: facts and arithmetic
only.

## Daily build

- **The Action** — `.github/workflows/grid.yml` re-pulls, rebuilds, and redeploys the site
  every day.
- **Dry runs** — `gh workflow run grid.yml --ref <branch> -f dry_run=true` pulls, builds, and
  runs every check with nothing committed or deployed; any run on a branch other than
  `main` does the same automatically, so a branch can never push data to `main`.
- **Source status** — `data/run-status.json`, written and committed each run, records
  ok/failed per data source, the newest filing date found for each, and whether the data has
  gone stale — so a source that fails quietly (old behavior: keep last data, stay green,
  nobody notices) now shows up instead of hiding.
- **Link picture** — `python -m datproof_feed.og` draws `site/og.png`, the 1200x630 picture shown
  when the page is shared, from the same feed; a failed build keeps yesterday's picture.

## Also here: the bitcoin purchase grid

Every disclosed bitcoin purchase by Strategy, Strive and Metaplanet since 2020 on one activity
grid, each square linked to the filing behind it, with the funding beside the buys. Served at
https://datproof.com/grid/ and rebuilt by the same daily job.

- **The data** — `data/moves/*.csv`: one row per disclosed move (BTC buy or ATM sale) for
  Strategy, Strive, and Metaplanet, each with date, amounts, and its `source_url`. What
  can't be sourced from a filing isn't in the data.
- **The pullers** — `scripts/pull_mstr.py`, `pull_asst.py`, `pull_metaplanet.py` read the
  companies' disclosures; `scripts/build_grid_site.py` renders `site/grid/index.html` (served at `/grid/`) from the
  CSVs plus a keyless BTC ticker (`scripts/fetch_ticker.py`).

## Visitor count (off)

Set `site/config.json` to `{"counter": {"provider": "goatcounter", "code": "<your site code>"}}` (or `"cloudflare"` with the 32-character token) and the next daily build adds that one cookie-free counter script to the home page.
Leave `provider` empty and nothing is added; any other provider, or a code that is not a plain site code or token, stops the page build.

## Run it locally

```bash
python3 -m datproof_feed.pages          # home page, index.md, llms.txt, sitemap.xml
python3 scripts/build_grid_site.py      # the grid page at /grid/
python3 -m http.server 8471 --directory site
```

## Repo notes

- `archive/2026-07-rating-agency/` — DATproof's first concept (A–F evidence grades),
  retired 2026-07-30 and kept for the record.
- `archive/workflows/daily-brief.yml` — that concept's workflow, moved out of `.github/workflows/`
  so it can no longer run: one manual run rebuilt the retired pages over `site/index.html` and
  published them. Its scripts (`scripts/build_site.py`, `scripts/build_landing.py`, `datproof/`) stay.
- Tests live in `tests/`.
- **Moving the install pin.** The install command names one fixed commit (`SERVER_PIN` in `datproof_feed/pages.py`).
  1. Merge the tool server change to `main` first; the pin must point at a commit on `main`.
  2. Set `SERVER_PIN` to that commit's full hash and replace the old hash in `README.md` and `site/index.html`.
  3. Run `python3 -m datproof_feed.pages` to rewrite `index.md` and `llms.txt`, then the tests.
  4. `tests/test_install_pin.py` fails if any copy still names another commit or the commit is missing.

Built by [Lucas Cashwell](https://github.com/lucascashwell3-ai) · part of the `-proof`
family (Skillproof · Modelproof).
