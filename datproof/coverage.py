"""Years a company's preferred dividends stay paid, by each company's own published formula.

Both companies publish the same shape of number:

  Strive, "Total Dividend Coverage" (strive.com/treasury):
      (bitcoin x price + cash + marketable securities) / (SATA shares x $100 x SATA rate)
  Strategy, "Duration" (strategy.com):
      (bitcoin x price + USD Reserve + USD Cash) / annual preferred dividends and debt interest

So one function answers both: swap in any bitcoin price and the years come out. site/coverage.js
holds the same arithmetic for the slider; tests/test_credit.py keeps the two in step.
"""
from __future__ import annotations

SATA_STATED_AMOUNT = 100.0


def years_covered(btc: float, btc_price: float, usd_assets: float, annual_obligation: float) -> float:
    """Treasury assets at `btc_price` divided by one year of dividend (and interest) payments."""
    if annual_obligation <= 0:
        raise ValueError("annual obligation must be positive")
    return (btc * btc_price + usd_assets) / annual_obligation


def strive_annual_dividend(sata_shares: float, rate: float, stated: float = SATA_STATED_AMOUNT) -> float:
    """SATA shares x $100 stated amount x the annual rate (0.13 for 13%)."""
    return sata_shares * stated * rate


def strive_years(strive: dict, btc_price: float) -> float:
    """strive = the `strive` block of data/credit.json."""
    return years_covered(strive["btc"], btc_price, strive["cash"] + strive["securities"],
                         strive_annual_dividend(strive["sata_shares"], strive["sata_rate"]))


def strategy_years(strategy: dict, btc_price: float) -> float:
    """strategy = the `strategy` block of data/credit.json."""
    return years_covered(strategy["btc"], btc_price, strategy["usd_assets"], strategy["annual_obligation"])
