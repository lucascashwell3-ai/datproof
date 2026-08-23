# moves CSV schema (one file per company, e.g. MSTR.csv)
date,ticker,type,instrument,units,usd,btc,btc_avg_usd,period_start,period_end,source_url,notes

- date: filing date (YYYY-MM-DD). period_start/period_end: the window the filing covers.
- type: btc_buy | atm_sale
- instrument: BTC for buys; for ATM sales: common | STRK | STRF | STRC | STRD | SATA
- units: shares sold (atm_sale) — blank for buys
- usd: $ raised (atm_sale) or $ spent (btc_buy), in whole dollars
- btc: bitcoin bought (btc_buy) — blank for sales
- btc_avg_usd: average price per BTC as stated in the filing
- source_url: the EDGAR filing (or official IR release) — REQUIRED. No source, no row.
- Rule: never infer or estimate a number. Blank + note beats a guess.
