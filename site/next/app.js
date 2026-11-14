/* DATproof home page. Every number comes from the daily feed at load time; none is typed into the page. */
(function () {
  "use strict";

  // ---- compare: a port of datproof_feed/compare.py. Keep the two in step. ----
  var KINDS = ["preferred", "tbill", "money_market", "usdc_lending"];
  var FLAG_ORDER = ["price_moves", "issuer_sets_rate", "short_history", "thin_trading", "payment_gap",
    "no_payment_in_window", "stale", "not_bank_insured", "smart_contract_risk"];
  var SHORT_HISTORY_DAYS = 90, THIN_TRADING_SHARE = 0.01;
  var NOTE = "Facts and arithmetic only. Not advice. A preferred stock's price can fall below its " +
    "$100 par and its issuer sets the rate; income figures assume today's yield holds.";

  function isObj(x) { return x !== null && typeof x === "object" && !Array.isArray(x); }
  function v(x) { return isObj(x) ? (x.value === undefined ? null : x.value) : (x === undefined ? null : x); }
  function stale() { for (var i = 0; i < arguments.length; i++) if (isObj(arguments[i]) && arguments[i].stale) return true; return false; }
  function src(x) { return isObj(x) ? (x.source === undefined ? null : x.source) : null; }
  function round(x, n) { return Number(x.toFixed(n)); }
  function g(x) { return String(Number(x.toPrecision(6))); }  // Python's f"{x:g}" for ordinary sizes
  function pct(x) { return g(x) + "%"; }
  function order(flags) {
    var known = FLAG_ORDER.filter(function (f) { return flags.indexOf(f) >= 0; });
    var rest = flags.filter(function (f) { return FLAG_ORDER.indexOf(f) < 0; }).sort();
    return known.concat(rest.filter(function (f, i, a) { return a.indexOf(f) === i; }));
  }
  function income(amount, y, days) { return y === null ? null : round(amount * y / 100 * days / 365, 2); }
  function addDays(iso, n) {
    var d = new Date(iso + "T00:00:00Z"); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10);
  }
  function add(set, f) { if (set.indexOf(f) < 0) set.push(f); }

  function check(amount, days, maxDrop, kinds) {
    if (typeof amount !== "number" || !isFinite(amount) || amount <= 0) throw new Error("amount_usd must be a number above 0");
    if (typeof days !== "number" || !Number.isInteger(days) || days <= 0) throw new Error("days must be a whole number above 0");
    if (typeof maxDrop !== "number" || !isFinite(maxDrop) || maxDrop < 0) throw new Error("max_drop_pct must be a number, 0 or more");
    var bad = kinds.filter(function (k) { return KINDS.indexOf(k) < 0; });
    if (bad.length) throw new Error("unknown kinds " + bad.join(", "));
  }

  function instrumentFlags(ins, amount, days, asOf) {
    var flags = (ins.flags || []).slice();
    if (ins.kind === "preferred") { add(flags, "price_moves"); add(flags, "issuer_sets_rate"); }
    if ((ins.trading_days || 0) < SHORT_HISTORY_DAYS) add(flags, "short_history");
    var vol = v(ins.avg_volume_30d), close = v(ins.close_usd);
    if (vol === null || close === null || amount > THIN_TRADING_SHARE * vol * close) add(flags, "thin_trading");
    if (((ins.payments || {}).gaps || []).length) add(flags, "payment_gap");
    var nxt = ins.next_pay_date;
    if (!nxt || nxt > addDays(asOf, days)) add(flags, "no_payment_in_window");
    if (stale(ins.close_usd, ins.stated_rate_pct, ins.yield_pct, ins.worst_drop_pct, ins.avg_volume_30d)) add(flags, "stale");
    return order(flags);
  }

  function benchmarkFlags(b) {
    var flags = (b.flags || []).slice();
    if (b.kind === "money_market") add(flags, "not_bank_insured");
    if (b.kind === "usdc_lending") add(flags, "smart_contract_risk");
    if (stale(b.yield_pct)) add(flags, "stale");
    return order(flags);
  }

  function excludedReason(ins, kinds, maxDrop) {
    if (kinds.indexOf(ins.kind) < 0) return "kind " + ins.kind + " is not in the kinds the account can hold";
    var y = ins.yield_pct || {};
    if (v(y) === null) return "no yield today: " + (y.reason || "unknown");
    var d = ins.worst_drop_pct || {};
    if (v(d) === null) return "worst drop unknown: " + (d.reason || "unknown");
    if (v(d) > maxDrop) return "worst drop " + pct(round(v(d), 2)) + " is more than " + pct(maxDrop);
    return null;
  }

  function compare(feed, amount, days, maxDrop, kinds) {
    kinds = kinds.filter(function (k, i, a) { return a.indexOf(k) === i; }).sort();
    check(amount, days, maxDrop, kinds);
    var asOf = feed.date, options = [], excluded = [];
    (feed.instruments || []).forEach(function (ins) {
      var reason = excludedReason(ins, kinds, maxDrop);
      if (reason) { excluded.push({ ticker: ins.ticker, reason: reason }); return; }
      var y = round(v(ins.yield_pct), 3), close = ins.close_usd || {}, rate = ins.stated_rate_pct || {};
      options.push({
        ticker: ins.ticker, name: ins.name === undefined ? null : ins.name, kind: ins.kind,
        yield_pct: y, est_income_usd: income(amount, y, days),
        worst_drop_pct: round(v(ins.worst_drop_pct), 3),
        close_usd: v(close), par_usd: ins.par_usd === undefined ? null : ins.par_usd, stated_rate_pct: v(rate),
        schedule: ins.schedule === undefined ? null : ins.schedule,
        next_pay_date: ins.next_pay_date === undefined ? null : ins.next_pay_date,
        flags: instrumentFlags(ins, amount, days, asOf),
        as_of: close.as_of === undefined ? null : close.as_of, source: src(close), rate_source: src(rate)
      });
    });
    options.sort(function (a, b) { return b.yield_pct - a.yield_pct || (a.ticker < b.ticker ? -1 : a.ticker > b.ticker ? 1 : 0); });
    excluded.sort(function (a, b) { return a.ticker < b.ticker ? -1 : a.ticker > b.ticker ? 1 : 0; });
    var benchmarks = (feed.benchmarks || []).map(function (b) {
      var yv = b.yield_pct || {}, y = v(yv) === null ? null : round(v(yv), 3);
      var row = { id: b.id, kind: b.kind, name: b.name === undefined ? null : b.name, yield_pct: y,
        est_income_usd: income(amount, y, days), holdable: kinds.indexOf(b.kind) >= 0,
        flags: benchmarkFlags(b), as_of: yv.as_of === undefined ? null : yv.as_of, source: src(yv) };
      if (y === null) row.reason = yv.reason === undefined ? null : yv.reason;
      return row;
    });
    return { as_of: feed.date, inputs: { amount_usd: amount, days: days, max_drop_pct: maxDrop, kinds: kinds },
      options: options, benchmarks: benchmarks, excluded: excluded, note: NOTE };
  }

  var api = { compare: compare, KINDS: KINDS };
  if (typeof module !== "undefined" && module.exports) { module.exports = api; return; }

  // ---- page ----
  var $ = function (s) { return document.querySelector(s); };
  var LEAD = ["STRC", "SATA", "SATS"];
  var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  var MONTHS_LONG = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
  var SVGNS = "http://www.w3.org/2000/svg";

  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
  function day(iso) { if (!iso) return ""; var p = iso.slice(0, 10).split("-"); return +p[2] + " " + MONTHS[+p[1] - 1] + " " + p[0]; }
  function monthName(iso) { var p = iso.split("-"); return MONTHS_LONG[+p[1] - 1]; }
  function n(x, d) { return x.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d }); }
  function usd(x, d) { return "$" + n(x, d || 0); }
  function f1(x) { return n(x, 1); }
  function host(u) { try { return new URL(u).host.replace(/^www\./, ""); } catch (e) { return u || ""; } }
  function has(x) { return v(x) !== null; }
  function el(tag, attrs, text) {
    var e = document.createElementNS(SVGNS, tag);
    for (var k in attrs) e.setAttribute(k, attrs[k]);
    if (text !== undefined) e.textContent = text;
    return e;
  }

  var feed, scen, closes = {}, AMOUNT = 10000;

  function bench(id) { return (feed.benchmarks || []).filter(function (b) { return b.id === id; })[0]; }
  function inst(t) { return (feed.instruments || []).filter(function (i) { return i.ticker === t; })[0]; }
  function lead() { return LEAD.map(inst).filter(function (i) { return i && has(i.yield_pct); }); }
  function inflation() { var x = feed.inflation_yoy_pct; return x && has(x) ? x : null; }
  function year() { return (scen.lookback || []).filter(function (l) { return l.days === 365; })[0]; }

  // ---------- 1. first screen ----------
  function renderHero() {
    var tb = bench("tbill_4w"), inf = inflation(), dc = lead();
    if (tb && has(tb.yield_pct)) $("#hl-bill").textContent = "T-bills pay " + f1(v(tb.yield_pct)) + "%.";
    if (inf) { var hi = $("#hl-inf"); hi.textContent = "Inflation takes " + f1(v(inf)) + "%."; hi.hidden = false; }
    if (dc.length) {
      var ys = dc.map(function (i) { return Math.round(v(i.yield_pct)); });
      var lo = Math.min.apply(null, ys), hiY = Math.max.apply(null, ys);
      $("#hl-dc").textContent = "Digital credit pays " + (lo === hiY ? lo : lo + "\u00a0to\u00a0" + hiY) + "%.";
    }
    var px = dc.map(function (i) { return i.close_usd.as_of; }).sort().pop();
    $("#asof").textContent = "Data for " + day(feed.date) + (px ? " · prices at the " + day(px) + " close" : "") +
      (inf ? " · inflation is US CPI, " + monthName(inf.month) + " " + inf.month.slice(0, 4) + " vs a year earlier" : "");
  }

  function earnRows() {
    var rows = [], y = year(), tb = bench("tbill_4w"), mm = bench("mmf_vmfxx");
    if (tb && has(tb.yield_pct)) rows.push({ name: "T-bill", note: "4-week, at today's rate", usd: AMOUNT * v(tb.yield_pct) / 100 });
    if (mm && has(mm.yield_pct)) rows.push({ name: "Money market", note: "Vanguard VMFXX, at today's rate", usd: AMOUNT * v(mm.yield_pct) / 100 });
    lead().forEach(function (i) {
      var past = y && y.instruments.filter(function (r) { return r.ticker === i.ticker; })[0];
      if (past && !past.skipped && past.dividends_usd > 0)
        rows.push({ name: i.ticker, note: "dividends paid, past year", usd: past.dividends_usd, dc: true });
      else rows.push({ name: i.ticker, note: "at today's rate", usd: AMOUNT * v(i.yield_pct) / 100, dc: true });
    });
    return rows;
  }

  function drawEarn(first) {
    var box = $("#earn-chart"), rows = earnRows(), inf = inflation();
    var W = Math.max(280, box.clientWidth), narrow = W < 620;
    var L = narrow ? 0 : 210, top = inf ? 34 : 6, rh = narrow ? 62 : 54, bh = narrow ? 18 : 24;
    var H = top + rows.length * rh;
    var max = Math.max.apply(null, rows.map(function (r) { return r.usd; }));
    var room = narrow ? 64 : 78;
    function x(u) { return L + (u / max) * (W - L - room); }
    var svg = el("svg", { viewBox: "0 0 " + W + " " + H, width: W, height: H });
    var infUsd = inf ? AMOUNT * v(inf) / 100 : null;
    rows.forEach(function (r, i) {
      var y0 = top + i * rh, by = narrow ? y0 + 30 : y0 + (rh - bh) / 2;
      if (narrow) {
        var t = el("text", { x: 0, y: y0 + 18 });
        t.appendChild(el("tspan", { class: "c-name" }, r.name));
        t.appendChild(el("tspan", { class: "c-note", dx: 8 }, r.note));
        svg.appendChild(t);
      } else {
        svg.appendChild(el("text", { x: 0, y: by + bh / 2 - 2, class: "c-name" }, r.name));
        svg.appendChild(el("text", { x: 0, y: by + bh / 2 + 14, class: "c-note" }, r.note));
      }
      svg.appendChild(el("rect", { x: L, y: by, width: Math.max(2, x(r.usd) - L), height: bh, rx: 2, class: "c-bar" + (r.dc ? " dc" : "") }));
      svg.appendChild(el("text", { x: x(r.usd) + 10, y: by + bh / 2 + 5, class: "c-val" + (r.dc ? " dc" : "") }, usd(r.usd)));
    });
    if (infUsd !== null) {
      var xi = x(infUsd);
      if (narrow) rows.forEach(function (r, i) {
        var by = top + i * rh + 30;
        svg.appendChild(el("line", { x1: xi, x2: xi, y1: by - 6, y2: by + bh + 6, class: "c-inf" }));
      });
      else svg.appendChild(el("line", { x1: xi, x2: xi, y1: top - 10, y2: H - 4, class: "c-inf" }));
      svg.appendChild(el("text", { x: xi - 6, y: top - 18, class: "c-inf-t", "text-anchor": narrow ? "start" : "end" }, "Inflation takes " + usd(infUsd)));
      if (narrow) svg.lastChild.setAttribute("x", Math.max(0, xi - 40));
    }
    box.innerHTML = "";
    box.appendChild(svg);
    box.setAttribute("aria-label", "What $10,000 earns in a year: " + rows.map(function (r) { return r.name + " " + usd(r.usd) + " (" + r.note + ")"; }).join("; ") +
      (infUsd !== null ? ". Inflation takes " + usd(infUsd) + "." : "."));
    if (first) box.classList.add("draw");
  }

  // ---------- 2. the three ----------
  function renderPanels() {
    var tb = bench("tbill_4w"), tbY = tb && has(tb.yield_pct) ? v(tb.yield_pct) : null;
    $("#panels").innerHTML = lead().map(function (i) {
      var y = v(i.yield_pct), pay = i.payments || {}, close = v(i.close_usd);
      var times = tbY ? '<p class="p-x">' + n(y / tbY, 1) + " times a T-bill</p>" : "";
      var row = pay.in_a_row ? n(pay.in_a_row, 0) + ((pay.gaps || []).length ? "" : ", none missed") : "";
      return '<article class="panel">' +
        '<div class="p-head"><h3 class="p-tk">' + esc(i.ticker) + '</h3><span class="p-iss">' + esc(i.issuer) + "</span></div>" +
        '<p class="p-yield">' + f1(y) + "%</p>" + times +
        '<dl class="p-facts">' +
        "<dt>Price today</dt><dd>" + (close !== null ? usd(close, 2) : "") + ' <span class="p-iss">of $' + n(i.par_usd, 0) + "</span></dd>" +
        "<dt>Pays</dt><dd>" + (i.schedule === "every business day" ? "Every business day" : esc(i.schedule || "")) + "</dd>" +
        "<dt>Dividends in a row</dt><dd>" + row + "</dd>" +
        "</dl></article>";
    }).join("");
    var rest = (feed.instruments || []).filter(function (i) { return LEAD.indexOf(i.ticker) < 0 && has(i.yield_pct); });
    $("#longer").innerHTML = rest.length ? '<span class="lg-t">Also in the feed: the longer-term preferreds. Fixed rate, paid quarterly, they trade further from $100.</span>' +
      rest.map(function (i) { return "<span><b>" + esc(i.ticker) + "</b> " + f1(v(i.yield_pct)) + "% · " + usd(v(i.close_usd), 2) + "</span>"; }).join("") : "";
  }

  // ---------- 3. paid through every dip ----------
  function drawPaid() {
    var wrap = $("#paid-charts"), out = [];
    ["STRC", "SATA"].forEach(function (t) {
      var i = inst(t), c = closes[t];
      if (!i || !c || !c.rows || c.rows.length < 20) return;
      out.push({ i: i, rows: c.rows, divs: (c.dividends || []) });
    });
    if (!out.length) { $("#paid").hidden = true; return; }
    if (!wrap.children.length) {
      wrap.innerHTML = out.map(function (o) {
        return '<div class="pc"><h3>' + esc(o.i.ticker) + '</h3><div class="chart" role="img"></div><p></p></div>';
      }).join("");
    }
    out.forEach(function (o, k) {
      var node = wrap.children[k], box = node.querySelector(".chart");
      var rows = o.rows, d0 = rows[0][0], d1 = rows[rows.length - 1][0];
      var paid = o.divs.filter(function (d) { return d.pay >= d0 && d.pay <= feed.date && d.usd > 0; });
      var vals = rows.map(function (r) { return r[1]; });
      var lowV = Math.min.apply(null, vals), highV = Math.max.apply(null, vals);
      var lo = Math.floor((lowV - 3) / 10) * 10, hi = Math.max(105, Math.ceil((highV + 2) / 5) * 5);
      var W = Math.max(280, box.clientWidth), H = W < 420 ? 220 : 260;
      var ml = 44, mr = 62, mt = 10, lane = 22, mb = 26;
      var ph = H - mt - lane - mb - 16;
      var t0 = Date.parse(d0), t1 = Date.parse(d1);
      function X(iso) { return ml + (Date.parse(iso) - t0) / (t1 - t0) * (W - ml - mr); }
      function Y(p) { return mt + (hi - p) / (hi - lo) * ph; }
      var svg = el("svg", { viewBox: "0 0 " + W + " " + H, width: W, height: H });
      for (var p = lo; p <= hi; p += 10) {
        if (p === 100) continue;
        svg.appendChild(el("line", { x1: ml, x2: W - mr, y1: Y(p), y2: Y(p), class: "c-grid" }));
        svg.appendChild(el("text", { x: ml - 8, y: Y(p) + 4, "text-anchor": "end", class: "c-tick" }, "$" + p));
      }
      svg.appendChild(el("line", { x1: ml, x2: W - mr, y1: Y(100), y2: Y(100), class: "c-par" }));
      svg.appendChild(el("text", { x: ml - 8, y: Y(100) + 4, "text-anchor": "end", class: "c-par-t" }, "$100"));
      var dpath = rows.map(function (r, j) { return (j ? "L" : "M") + X(r[0]).toFixed(1) + " " + Y(r[1]).toFixed(1); }).join("");
      svg.appendChild(el("path", { d: dpath, class: "c-line" }));
      var last = rows[rows.length - 1];
      svg.appendChild(el("circle", { cx: X(last[0]), cy: Y(last[1]), r: 4, class: "c-dot" }));
      svg.appendChild(el("text", { x: X(last[0]) + 9, y: Y(last[1]) - 2, class: "c-end" }, usd(last[1], 2)));
      svg.appendChild(el("text", { x: X(last[0]) + 9, y: Y(last[1]) + 13, class: "c-tick" }, "today"));
      var laneY = mt + ph + 14;
      svg.appendChild(el("text", { x: ml - 8, y: laneY + lane / 2 + 4, "text-anchor": "end", class: "c-tick paid-t" }, "Paid"));
      paid.forEach(function (d) {
        var xx = X(d.pay < d1 ? d.pay : d1);
        svg.appendChild(el("line", { x1: xx, x2: xx, y1: laneY, y2: laneY + lane, class: "c-div" }));
      });
      // month labels: every third month
      var start = new Date(t0), m = new Date(Date.UTC(start.getUTCFullYear(), start.getUTCMonth() + 1, 1));
      for (var q = 0; m.getTime() <= t1; q++, m.setUTCMonth(m.getUTCMonth() + 1)) {
        if (q % 3) continue;
        var iso = m.toISOString().slice(0, 10);
        svg.appendChild(el("text", { x: X(iso), y: H - 6, "text-anchor": "middle", class: "c-tick" },
          MONTHS[m.getUTCMonth()] + (m.getUTCMonth() === 0 ? " " + m.getUTCFullYear() : "")));
      }
      box.innerHTML = ""; box.appendChild(svg);
      var lowRow = rows.filter(function (r) { return r[1] === lowV; })[0];
      var none = !((o.i.payments || {}).gaps || []).length;
      var near = Math.abs(last[1] - 100) <= 3;
      box.setAttribute("aria-label", o.i.ticker + " price over the past year with " + paid.length + " dividends paid. Lowest close " + usd(lowV, 2) + " in " + monthName(lowRow[0]) + ", " + usd(last[1], 2) + " today.");
      node.querySelector("p").innerHTML = (none ? "Every dividend paid: <b>" + paid.length + " of " + paid.length + "</b> in the past year" : "<b>" + paid.length + "</b> dividends paid in the past year") +
        ", through a dip in " + monthName(lowRow[0]) + ". <b>" + usd(last[1], 2) + "</b> today" + (near ? ", back near $100." : ".");
    });
  }

  // ---------- 4. backed by bitcoin ----------
  function renderBacked() {
    var cov = feed.coverage && feed.coverage.issuers;
    if (!cov || !cov.length) { $("#backed").hidden = true; return; }
    var html = cov.map(function (c) {
      var yrs = c.years_of_dividends_covered, btc = c.btc_held, res = c.dividend_reserve_months;
      var big, what, two = "", srcs = [yrs, btc, res].filter(has);
      if (!srcs.length) return "";
      if (has(yrs)) {
        big = n(v(yrs), 1) + "<small>years</small>";
        what = "of dividends and interest covered by its bitcoin and cash. " + esc(c.issuer) + "'s own figure.";
        if (has(btc)) two = "<b>" + n(v(btc), 0) + "</b> bitcoin held";
      } else if (has(btc)) {
        big = n(v(btc), 0) + "<small>bitcoin</small>";
        what = "held by " + esc(c.issuer) + ", by its own count.";
        if (has(res)) two = "<b>" + n(v(res), 0) + " months</b> of dividends set aside in cash, " + esc(c.issuer) + "'s own figure";
      } else return "";
      var s = srcs[0];
      return '<div class="bk"><h3 class="bk-iss">' + esc(c.issuer) + '</h3><p class="bk-big">' + big + '</p><p class="bk-what">' + what + "</p>" +
        (two ? '<p class="bk-two">' + two + "</p>" : "") +
        '<p class="bk-src"><a href="' + esc(s.source) + '" rel="noopener">' + esc(host(s.source)) + "</a>, as of " + day(s.as_of) + "</p></div>";
    }).join("");
    if (!html) { $("#backed").hidden = true; return; }
    $("#backed-grid").innerHTML = html;
  }

  // ---------- 5. your numbers ----------
  function parseNum(s) { var x = Number(String(s).replace(/[$,\s]/g, "")); return isFinite(x) ? x : NaN; }
  function renderYours() {
    var amount = parseNum($("#in-amount").value), days = parseNum($("#in-days").value), out = $("#yours-out");
    if (!(amount > 0) || !(days > 0) || Math.floor(days) !== days) {
      out.innerHTML = '<p class="fine">Enter an amount above $0 and a whole number of days.</p>'; return;
    }
    var res = compare(feed, amount, days, 100, KINDS.slice());
    var rows = [], inf = inflation();
    var tb = res.benchmarks.filter(function (b) { return b.id === "tbill_4w"; })[0];
    if (inf) rows.push({ name: "Inflation takes", note: "US CPI, past year", y: v(inf), cls: "inf" });
    if (tb && tb.yield_pct !== null) rows.push({ name: "T-bill", note: "4-week", y: tb.yield_pct, usd: tb.est_income_usd });
    LEAD.forEach(function (t) {
      var o = res.options.filter(function (r) { return r.ticker === t; })[0];
      if (o) rows.push({ name: t, note: f1(o.yield_pct) + "% today", y: o.yield_pct, usd: o.est_income_usd, cls: "dc" });
    });
    rows.forEach(function (r) { if (r.usd === undefined) r.usd = round(amount * r.y / 100 * days / 365, 2); r.perDay = amount * r.y / 100 / 365; });
    var max = Math.max.apply(null, rows.map(function (r) { return r.usd; }));
    var big = amount * Math.max.apply(null, rows.map(function (r) { return r.y; })) / 100 / 365 >= 100;
    var label = days === 365 ? "In a year" : "In " + n(days, 0) + " days";
    out.innerHTML = '<div class="y-head"><span></span><span></span><span>' + label + "</span></div>" +
      rows.map(function (r) {
        return '<div class="y-row ' + (r.cls || "") + '"><span class="y-name">' + esc(r.name) + "<small>" + esc(r.note) + "</small></span>" +
          '<span class="y-track"><i style="width:' + Math.max(1, r.usd / max * 100).toFixed(2) + '%"></i></span>' +
          '<span class="y-n">' + usd(r.usd, r.usd >= 100 ? 0 : 2) + '<small class="y-d">' + usd(r.perDay, big ? 0 : 2) + " a day</small></span></div>";
      }).join("");
  }

  // ---------- 7. sources ----------
  function renderSources() {
    var items = [];
    function add2(label, x) { if (x && x.source) items.push([label, x.source, x.as_of]); }
    feed.benchmarks.forEach(function (b) { add2(b.name, b.yield_pct); });
    if (feed.inflation_yoy_pct) add2("US CPI-U, all items (" + (feed.inflation_yoy_pct.month || "") + " vs " + (feed.inflation_yoy_pct.year_ago_month || "") + ")", feed.inflation_yoy_pct);
    feed.instruments.forEach(function (i) {
      add2(i.ticker + " closing price", i.close_usd);
      add2(i.ticker + " dividend rate", i.stated_rate_pct);
    });
    LEAD.forEach(function (t) { var i = inst(t); if (i && i.dividends_source) items.push([t + " dividends paid", i.dividends_source, feed.date]); });
    ((feed.coverage || {}).issuers || []).forEach(function (c) {
      add2(c.issuer + " years of dividends covered", c.years_of_dividends_covered);
      add2(c.issuer + " bitcoin held", c.btc_held);
      add2(c.issuer + " dividend reserve", c.dividend_reserve_months);
    });
    $("#sources-list").innerHTML = "<ul>" + items.map(function (s) {
      return "<li>" + esc(s[0]) + ': <a href="' + esc(s[1]) + '" rel="noopener">' + esc(host(s[1])) + "</a>" + (s[2] ? ", " + day(s[2]) : "") + "</li>";
    }).join("") + '<li>Method for every number: <a href="../v1/method.json">method.json</a></li></ul>';
  }

  function copy() {
    var text = $("#cmd").textContent, msg = $("#copy-msg"), btn = $("#copy");
    function blocked() {
      var r = document.createRange(); r.selectNodeContents($("#cmd"));
      var s = window.getSelection(); s.removeAllRanges(); s.addRange(r);
      msg.textContent = "This browser blocked copying. The command is selected: press Ctrl+C or Cmd+C.";
    }
    if (!navigator.clipboard || !window.isSecureContext) return blocked();
    navigator.clipboard.writeText(text).then(function () {
      btn.textContent = "Copied"; msg.textContent = "";
      setTimeout(function () { btn.textContent = "Copy"; }, 1800);
    }, blocked);
  }

  function getJSON(u) { return fetch(u, { cache: "no-cache" }).then(function (r) { if (!r.ok) throw new Error(u + " " + r.status); return r.json(); }); }
  function load(base) {
    return Promise.all([getJSON(base + "instruments.json"), getJSON(base + "scenarios.json")].concat(
      ["STRC", "SATA"].map(function (t) { return getJSON(base + "instrument/" + t + ".json").catch(function () { return null; }); })
    )).then(function (d) {
      // A feed built before inflation, coverage and daily closes were added cannot draw this page.
      if (!("inflation_yoy_pct" in d[0]) || !d[2] || !d[2].closes) throw new Error("older feed format");
      return d;
    });
  }

  function start(d) {
    feed = d[0]; scen = d[1];
    [d[2], d[3]].forEach(function (x) { if (x && x.closes) closes[x.ticker] = { rows: x.closes.rows, dividends: x.dividends }; });
    renderHero(); drawEarn(true); renderPanels(); drawPaid(); renderBacked(); renderYours(); renderSources();
    ["#in-amount", "#in-days"].forEach(function (s) { $(s).addEventListener("input", renderYours); });
    $("#f-yours").addEventListener("submit", function (e) { e.preventDefault(); });
    var w = window.innerWidth, t;
    window.addEventListener("resize", function () {
      if (window.innerWidth === w) return; w = window.innerWidth;
      clearTimeout(t); t = setTimeout(function () { drawEarn(false); drawPaid(); }, 120);
    });
  }

  $("#copy").addEventListener("click", copy);
  load("../v1/").catch(function () { return load("./v1-sample/"); }).then(start).catch(function (e) {
    $("#asof").innerHTML = '<span class="err">The feed did not load (' + esc(e.message) + "). Read the JSON files directly.</span>";
  });
})();
