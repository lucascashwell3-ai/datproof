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
  companies' disclosures; `scripts/build_grid_site.py` renders `site/index.html` from the
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

A free daily data feed for AI agents and the people who run them. It lists the Bitcoin
treasury preferred stocks (STRC, SATA, SATS, STRF, STRK, STRD) beside three benchmarks (the
4-week Treasury bill, a government money market fund, USDC lending on Aave), each with its
yield, its worst past-year price fall, its payment record and risk flags. Every number names
its source and date; a number that could not be fetched is empty, with the reason.

- **Files** (rebuilt each day): `https://lucascashwell3-ai.github.io/datproof/v1/` +
  `instruments.json`, `instrument/<TICKER>.json`, `changes.json`, `method.json` (every
  formula and flag in plain words), `status.json`, and the dated `days/<date>.json`.
- **Compare** takes an amount in dollars, how many days, the biggest price fall you accept,
  and what the account can hold (`preferred`, `tbill`, `money_market`, `usdc_lending`). It
  returns each option's yield and estimated income next to its flags, plus the benchmarks.

### Use it

```bash
# 1. Run the tool server for any MCP client (or, from a clone: python3 -m datproof_feed.server)
uvx --from git+https://github.com/lucascashwell3-ai/datproof datproof-mcp

# 2. Optional: add the Claude Code skill that walks through the questions
cp -r skills/park-idle-cash ~/.claude/skills/
```

It never holds or moves money, places no orders, and is not advice: facts and arithmetic
only.

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
