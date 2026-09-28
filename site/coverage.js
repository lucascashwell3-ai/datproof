// Years a company's preferred dividends stay paid at a given bitcoin price.
// Same arithmetic as datproof/coverage.py (kept in step by tests/test_credit.py):
//   (bitcoin x price + dollar assets) / one year of dividend (and interest) payments
(function (root) {
  // no positive obligation, no answer: NaN, which the page shows as "not published"
  function yearsCovered(btc, price, usdAssets, annualObligation) {
    if (!(annualObligation > 0)) return NaN;
    return (btc * price + usdAssets) / annualObligation;
  }
  function striveAnnualDividend(sataShares, rate) { return sataShares * 100 * rate; }
  function striveYears(s, price) {
    return yearsCovered(s.btc, price, s.cash + s.securities, striveAnnualDividend(s.sata_shares, s.sata_rate));
  }
  function strategyYears(s, price) {
    return yearsCovered(s.btc, price, s.usd_assets, s.annual_obligation);
  }
  var api = { yearsCovered: yearsCovered, striveAnnualDividend: striveAnnualDividend,
              striveYears: striveYears, strategyYears: strategyYears };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.Coverage = api;
})(this);
