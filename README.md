# DATproof — bitcoin is eating corporate treasuries

**[Live site →](https://lucascashwell3-ai.github.io/datproof/)**

Public companies are moving their treasuries into bitcoin. DATproof shows it happening,
day by day: every disclosed BTC purchase since 2020 on one activity grid, every square
linked to the filing behind it. Beside the buys, the funding: at-the-market share sales
and the digital credit instruments (STRC, SATA) that raise the cash.

## How it works

- **The data** — `data/moves/*.csv`: one row per disclosed move (BTC buy or ATM sale) for
  Strategy, Strive, and Metaplanet, each with date, amounts, and its `source_url`. What
  can't be sourced from a filing isn't in the data.
- **The pullers** — `scripts/pull_mstr.py`, `pull_asst.py`, `pull_metaplanet.py` read the
  companies' disclosures; `scripts/build_grid_site.py` renders `site/index.html` from the
  CSVs plus a keyless BTC ticker (`scripts/fetch_ticker.py`).
- **The Action** — `.github/workflows/grid.yml` re-pulls, rebuilds, and redeploys the site
  every day.

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
