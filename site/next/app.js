/* DATproof home page. Every number comes from the daily feed at load time; none is typed into the page. */
(function () {
  "use strict";

  // ---- compare: a port of datproof_feed/compare.py. Keep the two in step. ----
  var KINDS = ["preferred", "tbill", "money_market", "usdc_lending"];
  var FLAG_ORDER = ["price_moves", "issuer_sets_rate", "short_history", "no_hold_odds", "thin_trading",
    "payment_gap", "no_payment_in_window", "stale", "not_bank_insured", "smart_contract_risk"];
  var SHORT_HISTORY_DAYS = 90, THIN_TRADING_SHARE = 0.01;
  var MIN_HOLDS = 60, PAST_YEAR_DAYS = 360, PROJECT_MONTHS = { monthly: 1, quarterly: 3 };
  var NOTE = "Facts and arithmetic only. Not advice. A preferred stock's price can fall below its " +
    "$100 par and its issuer sets the rate; income figures assume today's yield holds.";
  var HOLD_NOTE = "Hold odds are how past holds of the same length turned out, from daily closes and paid " +
    "dividends. Past results do not predict future results.";

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

  function daysBetween(a, b) { return Math.round((Date.parse(b + "T00:00:00Z") - Date.parse(a + "T00:00:00Z")) / 864e5); }
  function addMonths(iso, n) {
    var p = iso.split("-").map(Number), t = p[1] - 1 + n, y = p[0] + Math.floor(t / 12), m = t - 12 * Math.floor(t / 12) + 1;
    var last = new Date(Date.UTC(y, m, 0)).getUTCDate();
    var monthEnd = addDays(iso, 1).slice(5, 7) !== iso.slice(5, 7);
    var d = monthEnd ? last : Math.min(p[2], last);
    return y + "-" + (m < 10 ? "0" : "") + m + "-" + (d < 10 ? "0" : "") + d;
  }
  function payInHold(ins, asOf, days) {
    var end = addDays(asOf, days), nxt = ins.next_pay_date;
    if (nxt) return [nxt <= end, "declared next pay date " + nxt];
    var sched = ins.schedule, last = (ins.payments || {}).last_paid;
    if (PROJECT_MONTHS.hasOwnProperty(sched) && last) {
      var d = last;
      while (d <= asOf) d = addMonths(d, PROJECT_MONTHS[sched]);
      return [d <= end, "next pay date " + d + " projected from the " + sched + " schedule (last paid " + last + ")"];
    }
    return [false, "no declared or projected pay date"];
  }
  function share(k, n) { return Math.floor((2000 * k + n) / (2 * n)) / 10; }
  function whole(k, n) { return Math.floor((200 * k + n) / (2 * n)); }
  function median(xs) {
    var s = xs.slice().sort(function (a, b) { return a - b; }), m = Math.floor(s.length / 2);
    return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
  }
  function holds(ins, days) {
    var rows = ((ins.closes || {}).rows || []).map(function (r) { return [String(r[0]).slice(0, 10), Number(r[1])]; });
    var divs = (ins.dividends || []).map(function (x) { return [x.ex, Number(x.usd)]; });
    if (!rows.length) return [];
    var last = rows[rows.length - 1][0], out = [], j = 0;
    for (var i = 0; i < rows.length; i++) {
      var d0 = rows[i][0], c0 = rows[i][1], end = addDays(d0, days);
      if (end > last) break;
      j = Math.max(j, i);
      while (j + 1 < rows.length && rows[j + 1][0] <= end) j++;
      var dv = divs.reduce(function (s, x) { return x[0] > d0 && x[0] <= end ? s + x[1] : s; }, 0);
      out.push([(rows[j][1] - c0 + dv) / c0 * 100, d0]);
    }
    return out;
  }
  function holdOdds(ins, days, tb) {
    var rows = (ins.closes || {}).rows || [];
    if (!rows.length) return [null, "no daily closes in this feed file"];
    var hs = holds(ins, days), n = hs.length;
    if (n < MIN_HOLDS) return [null, "not enough history: " + n + " past holds of " + days + " days fit in " + rows.length +
      " trading days of closes; " + MIN_HOLDS + " are needed"];
    var worst = hs[0];
    hs.forEach(function (h) { if (h[0] < worst[0]) worst = h; });
    var res = hs.map(function (h) { return h[0]; });
    var hurdle = tb === null ? null : tb * days / 365;
    var beat = hurdle === null ? null : res.filter(function (r) { return r > hurdle; }).length;
    var lost = res.filter(function (r) { return r < 0; }).length;
    return [{ days: days, holds: n, bought_from: hs[0][1], bought_to: hs[n - 1][1],
      closes_from: String(rows[0][0]).slice(0, 10),
      tbill_pct: tb, tbill_hold_pct: hurdle === null ? null : round(hurdle, 3),
      beat_tbill: beat, beat_tbill_pct: beat === null ? null : share(beat, n),
      lost: lost, lost_pct: share(lost, n),
      median_pct: round(median(res), 2), worst_pct: round(worst[0], 2), worst_bought: worst[1] }, null];
  }
  function tbillPct(feed) {
    var b = (feed.benchmarks || []).filter(function (x) { return x.id === "tbill_4w"; })[0];
    return b ? v(b.yield_pct) : null;
  }
  function oddsFor(ins, days, tb) {
    if (((ins.closes || {}).rows || []).length) return holdOdds(ins, days, tb);
    var pub = (ins.hold_odds || {})[String(days)];
    if (pub !== undefined && pub !== null) return pub.reason ? [null, pub.reason] : [pub, null];
    return [null, "no daily closes in this feed file; instrument/<TICKER>.json carries them"];
  }
  function signed(x) { return (x >= 0 ? "+" : "-") + Math.abs(x).toFixed(2) + "%"; }
  function summaryLine(ticker, o, asOf) {
    var span = daysBetween(o.closes_from, asOf) >= PAST_YEAR_DAYS ? "over the past year" : "since " + o.closes_from;
    var beat = o.beat_tbill === null ? "beat a T-bill: unknown (no T-bill rate today)" :
      "beat a T-bill " + whole(o.beat_tbill, o.holds) + "% of the time";
    return ticker + ", " + o.days + "-day holds " + span + ": " + beat + ", lost money " + whole(o.lost, o.holds) +
      "% of the time, middle result " + signed(o.median_pct) + ", worst " + signed(o.worst_pct) + ".";
  }
  function profile(ins) {
    var p = ins.profile;
    if (!isObj(p)) return null;
    var facts = ["rate_type", "issuer_aims_price_near_100", "pay_schedule"], out = {}, srcs = [];
    facts.forEach(function (f) { out[f] = v(p[f]); });
    out.built_for = p.built_for === undefined ? null : p.built_for;
    facts.forEach(function (f) { var u = src(p[f]); if (u && srcs.indexOf(u) < 0) srcs.push(u); });
    out.sources = srcs;
    return out;
  }

  function instrumentFlags(ins, amount, days, asOf) {
    var flags = (ins.flags || []).slice();
    if (ins.kind === "preferred") { add(flags, "price_moves"); add(flags, "issuer_sets_rate"); }
    if ((ins.trading_days || 0) < SHORT_HISTORY_DAYS) add(flags, "short_history");
    var vol = v(ins.avg_volume_30d), close = v(ins.close_usd);
    if (vol === null || close === null || amount > THIN_TRADING_SHARE * vol * close) add(flags, "thin_trading");
    if (((ins.payments || {}).gaps || []).length) add(flags, "payment_gap");
    if (!payInHold(ins, asOf, days)[0]) add(flags, "no_payment_in_window");
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
    var asOf = feed.date, options = [], excluded = [], tb = tbillPct(feed);
    (feed.instruments || []).forEach(function (ins) {
      var reason = excludedReason(ins, kinds, maxDrop);
      if (reason) { excluded.push({ ticker: ins.ticker, reason: reason }); return; }
      var y = round(v(ins.yield_pct), 3), close = ins.close_usd || {}, rate = ins.stated_rate_pct || {};
      var ph = payInHold(ins, asOf, days), od = oddsFor(ins, days, tb);
      var flags = instrumentFlags(ins, amount, days, asOf);
      if (od[0] === null) flags = order(flags.concat(["no_hold_odds"]));
      options.push({
        ticker: ins.ticker, name: ins.name === undefined ? null : ins.name, kind: ins.kind,
        yield_pct: y, est_income_usd: ph[0] ? income(amount, y, days) : 0,
        est_income_reason: ph[0] ? null : "no payment lands inside the " + days + " days: " + ph[1],
        pay_in_hold: ph[0], pay_in_hold_basis: ph[1],
        worst_drop_pct: round(v(ins.worst_drop_pct), 3),
        hold_odds: od[0], hold_odds_reason: od[1], profile: profile(ins),
        close_usd: v(close), par_usd: ins.par_usd === undefined ? null : ins.par_usd, stated_rate_pct: v(rate),
        schedule: ins.schedule === undefined ? null : ins.schedule,
        next_pay_date: ins.next_pay_date === undefined ? null : ins.next_pay_date,
        flags: flags,
        as_of: close.as_of === undefined ? null : close.as_of, source: src(close), rate_source: src(rate)
      });
    });
    function tick(a, b) { return a.ticker < b.ticker ? -1 : a.ticker > b.ticker ? 1 : 0; }
    options.sort(function (a, b) {
      if (!!a.hold_odds !== !!b.hold_odds) return a.hold_odds ? -1 : 1;
      if (a.hold_odds) return b.hold_odds.median_pct - a.hold_odds.median_pct || tick(a, b);
      return b.yield_pct - a.yield_pct || tick(a, b);
    });
    excluded.sort(tick);
    var benchmarks = (feed.benchmarks || []).map(function (b) {
      var yv = b.yield_pct || {}, y = v(yv) === null ? null : round(v(yv), 3);
      var row = { id: b.id, kind: b.kind, name: b.name === undefined ? null : b.name, yield_pct: y,
        est_income_usd: income(amount, y, days), holdable: kinds.indexOf(b.kind) >= 0,
        flags: benchmarkFlags(b), as_of: yv.as_of === undefined ? null : yv.as_of, source: src(yv) };
      if (y === null) row.reason = yv.reason === undefined ? null : yv.reason;
      return row;
    });
    var summary = options.filter(function (o) { return o.hold_odds; }).map(function (o) { return summaryLine(o.ticker, o.hold_odds, asOf); });
    return { as_of: feed.date, inputs: { amount_usd: amount, days: days, max_drop_pct: maxDrop, kinds: kinds },
      options: options, summary: summary, benchmarks: benchmarks, excluded: excluded, note: NOTE, hold_odds_note: HOLD_NOTE };
  }

  var api = { compare: compare, KINDS: KINDS };
  if (typeof module !== "undefined" && module.exports) { module.exports = api; return; }

  // ---- page ----
  var $ = function (s) { return document.querySelector(s); };
  var $$ = function (s) { return Array.prototype.slice.call(document.querySelectorAll(s)); };
  var LEAD = ["STRC", "SATA", "SATS"];
  var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  var MONTHS_LONG = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
  var SVGNS = "http://www.w3.org/2000/svg";
  var CASH_SHARE = 0.6;  // the example account in "Better risk-adjusted returns"

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

  // ---------- dithered shading: 4x4 ordered (Bayer) dots, 2px cells, flat colour only ----------
  // Level k (1-16) turns on the cells whose threshold is below k, so every level contains the one under it
  // and a run of bands at rising levels reads as a 1-bit gradient. Green and blue only; orange stays flat.
  var BAYER = [0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5], CELL = 2;
  function dithered() { return document.documentElement.getAttribute("data-color") !== "orange"; }
  function ditherDefs(svg, id, cls) {
    var defs = el("defs", {});
    for (var k = 1; k <= 16; k++) {
      var d = "";
      for (var i = 0; i < 16; i++) if (BAYER[i] < k) d += "M" + (i % 4) * CELL + " " + Math.floor(i / 4) * CELL + "h" + CELL + "v" + CELL + "h-" + CELL + "z";
      var p = el("pattern", { id: id + k, width: 4 * CELL, height: 4 * CELL, patternUnits: "userSpaceOnUse" });
      p.appendChild(el("path", { d: d, class: cls }));
      defs.appendChild(p);
    }
    svg.appendChild(defs);
  }
  // Backdrop behind the first screen: dots thin out from the top-right corner.
  function drawHeroDither() {
    var old = $(".dz-hero"); if (old) old.parentNode.removeChild(old);
    if (!dithered()) return;
    var W = document.documentElement.clientWidth, R = Math.round(Math.min(W * 0.55, 780)), N = 12;
    var svg = el("svg", { class: "dz dz-hero", width: W, height: R, viewBox: "0 0 " + W + " " + R, "aria-hidden": "true", focusable: "false" });
    ditherDefs(svg, "dzh", "dz-ink");
    for (var b = 0; b < N; b++) svg.appendChild(el("circle", { cx: W, cy: 0, r: Math.round(R * (1 - b / N)), fill: "url(#dzh" + (1 + Math.round(b * 9 / (N - 1))) + ")" }));
    document.body.insertBefore(svg, document.body.firstChild);
  }
  // Top edge of "Connect your agent": a dot horizon that fades down into the section.
  function drawEdgeDither() {
    var sec = $("#agent"), old = sec.querySelector(".dz-edge"); if (old) sec.removeChild(old);
    if (!dithered()) return;
    var W = document.documentElement.clientWidth, H = 48, rows = 12;
    var svg = el("svg", { class: "dz dz-edge", width: W, height: H, viewBox: "0 0 " + W + " " + H, preserveAspectRatio: "none", "aria-hidden": "true", focusable: "false" });
    ditherDefs(svg, "dze", "dz-ink");
    for (var r = 0; r < rows; r++) svg.appendChild(el("rect", { x: 0, y: r * H / rows, width: W, height: H / rows, fill: "url(#dze" + Math.max(1, Math.round(10 - r * 10 / rows)) + ")" }));
    sec.insertBefore(svg, sec.firstChild);
  }
  // A digital-credit bar: dots fill in from sparse at the left to solid at the value end.
  function ditherBar(x0, y, w, h) {
    var g = el("g", { class: "c-bar dc dz-bar" }), LV = [2, 4, 8, 12, 16], N = LV.length;
    for (var s = 0; s < N; s++) {
      var a = Math.round(x0 + w * s / N), b = Math.round(x0 + w * (s + 1) / N);
      g.appendChild(el("rect", { x: a, y: y, width: b - a, height: h, fill: "url(#dzc" + LV[s] + ")" }));
    }
    return g;
  }

  function bench(id) { return (feed.benchmarks || []).filter(function (b) { return b.id === id; })[0]; }
  function inst(t) { return (feed.instruments || []).filter(function (i) { return i.ticker === t; })[0]; }
  function lead() { return LEAD.map(inst).filter(function (i) { return i && has(i.yield_pct); }); }
  function inflation() { var x = feed.inflation_yoy_pct; return x && has(x) ? x : null; }
  function year() { return (scen.lookback || []).filter(function (l) { return l.days === 365; })[0]; }
  function tbillY() { var tb = bench("tbill_4w"); return tb && has(tb.yield_pct) ? v(tb.yield_pct) : null; }
  function avgY() { var d = lead(); return d.length ? d.reduce(function (s, i) { return s + v(i.yield_pct); }, 0) / d.length : null; }
  function leadNames() { var t = lead().map(function (i) { return i.ticker; }); return t.length > 1 ? t.slice(0, -1).join(", ") + " and " + t[t.length - 1] : t.join(""); }

  // ---------- 1. first screen ----------
  function renderHero() {
    var tb = tbillY(), inf = inflation(), dc = lead();
    if (dc.length) {
      var ys = dc.map(function (i) { return Math.round(v(i.yield_pct)); });
      var lo = Math.min.apply(null, ys), hi = Math.max.apply(null, ys);
      $("#hl-range").textContent = (lo === hi ? lo : lo + "–" + hi) + "%";
    }
    var foot = [];
    if (tb !== null) foot.push("T-bills pay " + f1(tb) + "%.");
    if (inf) foot.push("Inflation runs " + f1(v(inf)) + "%.");
    $("#earn-foot").textContent = foot.join(" ");
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
    var infUsd = inf ? AMOUNT * v(inf) / 100 : null, dz = dithered();
    if (dz) ditherDefs(svg, "dzc", "dz-acc");
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
      if (r.dc && dz) svg.appendChild(ditherBar(L, by, Math.max(2, x(r.usd) - L), bh));
      else svg.appendChild(el("rect", { x: L, y: by, width: Math.max(2, x(r.usd) - L), height: bh, rx: 2, class: "c-bar" + (r.dc ? " dc" : "") }));
      svg.appendChild(el("text", { x: x(r.usd) + 10, y: by + bh / 2 + 5, class: "c-val" + (r.dc ? " dc" : "") }, usd(r.usd)));
    });
    if (infUsd !== null) {
      var xi = x(infUsd);
      if (narrow) rows.forEach(function (r, i) {
        var by = top + i * rh + 30;
        svg.appendChild(el("line", { x1: xi, x2: xi, y1: by - 6, y2: by + bh + 6, class: "c-inf" }));
      });
      else svg.appendChild(el("line", { x1: xi, x2: xi, y1: top - 10, y2: H - 4, class: "c-inf" }));
      svg.appendChild(el("text", { x: xi - 6, y: top - 18, class: "c-inf-t", "text-anchor": narrow ? "start" : "end" }, "Inflation: " + usd(infUsd)));
      if (narrow) svg.lastChild.setAttribute("x", Math.max(0, xi - 40));
    }
    box.innerHTML = "";
    box.appendChild(svg);
    box.setAttribute("aria-label", "Annual income on $10,000 of idle cash: " + rows.map(function (r) { return r.name + " " + usd(r.usd) + " (" + r.note + ")"; }).join("; ") +
      (infUsd !== null ? ". Inflation: " + usd(infUsd) + "." : "."));
    if (first) box.classList.add("draw");
  }

  // ---------- 2. the three ----------
  function renderPanels() {
    var tbY = tbillY();
    $("#panels").innerHTML = lead().map(function (i) {
      var y = v(i.yield_pct), pay = i.payments || {}, close = v(i.close_usd);
      var times = tbY ? '<p class="p-x"><span class="num">' + n(y / tbY, 1) + "×</span> a T-bill</p>" : "";
      var facts = [];
      facts.push(i.schedule === "every business day" ? "Pays every business day" : "Pays " + esc(i.schedule || ""));
      if (pay.in_a_row) facts.push('<b class="num">' + n(pay.in_a_row, 0) + "</b> dividends in a row");
      if (close !== null) facts.push('Price today <b class="num">' + usd(close, 2) + "</b>");
      return '<article class="panel">' +
        '<div class="p-head"><h3 class="p-tk">' + esc(i.ticker) + '</h3><span class="p-iss">' + esc(i.issuer) + "</span></div>" +
        '<p class="p-yield num">' + f1(y) + "%</p>" + times +
        '<ul class="p-facts">' + facts.map(function (f) { return "<li>" + f + "</li>"; }).join("") + "</ul></article>";
    }).join("");
    var rest = (feed.instruments || []).filter(function (i) { return LEAD.indexOf(i.ticker) < 0 && has(i.yield_pct); });
    $("#longer").innerHTML = rest.length ? '<span class="lg-t">Also covered: longer-term preferreds, paid quarterly.</span>' +
      rest.map(function (i) { return '<span><b>' + esc(i.ticker) + '</b> <span class="num">' + f1(v(i.yield_pct)) + "% · " + usd(v(i.close_usd), 2) + "</span></span>"; }).join("") : "";
  }

  // ---------- 3. liquid and steady ----------
  function nearShare(rows) { return rows.filter(function (r) { return Math.abs(r[1] - 100) <= 5; }).length / rows.length; }

  function drawPaid() {
    var wrap = $("#paid-charts"), out = [];
    ["STRC", "SATA"].forEach(function (t) {
      var i = inst(t), c = closes[t];
      if (!i || !c || !c.rows || c.rows.length < 20) return;
      out.push({ i: i, rows: c.rows, divs: (c.dividends || []) });
    });
    if (!out.length) { $("#paid").hidden = true; return; }
    var first = out[0];
    $("#paid-sub").textContent = "Sell any trading day. " + first.i.ticker + " closed within $5 of $100 on " +
      Math.round(nearShare(first.rows) * 100) + "% of trading days over the past year.";
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
      svg.appendChild(el("rect", { x: ml, y: Y(105), width: W - ml - mr, height: Y(95) - Y(105), class: "c-band" }));
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
      var start = new Date(t0), m = new Date(Date.UTC(start.getUTCFullYear(), start.getUTCMonth() + 1, 1));
      for (var q = 0; m.getTime() <= t1; q++, m.setUTCMonth(m.getUTCMonth() + 1)) {
        if (q % 3) continue;
        var iso = m.toISOString().slice(0, 10);
        svg.appendChild(el("text", { x: X(iso), y: H - 6, "text-anchor": "middle", class: "c-tick" },
          MONTHS[m.getUTCMonth()] + (m.getUTCMonth() === 0 ? " " + m.getUTCFullYear() : "")));
      }
      box.innerHTML = ""; box.appendChild(svg);
      var none = !((o.i.payments || {}).gaps || []).length;
      var share = Math.round(nearShare(rows) * 100);
      box.setAttribute("aria-label", o.i.ticker + " closing price over the past year, with " + paid.length + " dividends paid. Within $5 of $100 on " + share + "% of days. " + usd(last[1], 2) + " today.");
      node.querySelector("p").innerHTML = "Within $5 of $100 on <b>" + share + "%</b> of days. " +
        (none ? "<b>" + paid.length + "</b> of <b>" + paid.length + "</b> dividends paid." : "<b>" + paid.length + "</b> dividends paid.");
    });
  }

  // ---------- 4. better risk-adjusted returns ----------
  function renderLift() {
    var a = avgY();
    if (a === null) { $("#lift").hidden = true; return; }
    var cash = AMOUNT * CASH_SHARE, trade = AMOUNT - cash, extra = cash * a / 100;
    var tw = (1 - CASH_SHARE) * 100, cw = CASH_SHARE * 100;
    function bar(label, dc) {
      return '<div class="lf-row' + (dc ? " dc" : "") + '"><p class="lf-name">' + label + "</p>" +
        '<div class="lf-bar"><span class="lf-seg trade" style="width:' + tw + '%"><span>Trading ' + usd(trade) + "</span></span>" +
        '<span class="lf-seg cash" style="width:' + cw + '%"><span>Idle cash ' + usd(cash) + "</span></span></div>" +
        '<p class="lf-n num">' + (dc ? "+" + usd(extra) + "<small>a year</small>" : "$0<small>a year</small>") + "</p></div>";
    }
    $("#lift-out").innerHTML = bar("Cash at 0%", false) + bar("Cash in digital credit", true) +
      '<p class="fine">Example: a ' + usd(AMOUNT) + " account that sits " + Math.round(cw) + "% in cash on average. Extra income from the idle part only, at " +
      f1(a) + "%, today's average yield of " + leadNames() + ". That adds about " + f1(extra / AMOUNT * 100) + " points to the whole account's yearly return. Simple interest, before tax.</p>";
  }

  // ---------- 5. backed by bitcoin ----------
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
        if (has(btc)) two = '<b class="num">' + n(v(btc), 0) + "</b> bitcoin held";
      } else if (has(btc)) {
        big = n(v(btc), 0) + "<small>bitcoin</small>";
        what = "held by " + esc(c.issuer) + ", by its own count.";
        if (has(res)) two = '<b class="num">' + n(v(res), 0) + " months</b> of dividends set aside in cash, " + esc(c.issuer) + "'s own figure";
      } else return "";
      var s = srcs[0];
      return '<div class="bk"><h3 class="bk-iss">' + esc(c.issuer) + '</h3><p class="bk-big num">' + big + '</p><p class="bk-what">' + what + "</p>" +
        (two ? '<p class="bk-two">' + two + "</p>" : "") +
        '<p class="bk-src"><a href="' + esc(s.source) + '" rel="noopener">' + esc(host(s.source)) + "</a>, as of " + day(s.as_of) + "</p></div>";
    }).join("");
    if (!html) { $("#backed").hidden = true; return; }
    $("#backed-grid").innerHTML = html;
  }

  // ---------- 6. calculator ----------
  function parseNum(s) { var x = Number(String(s).replace(/[$,\s]/g, "")); return isFinite(x) ? x : NaN; }
  function money(x) { return x >= 100 ? usd(x) : usd(x, 2); }
  function renderCalc() {
    var amount = parseNum($("#in-amount").value), out = $("#calc-out"), a = avgY(), tb = tbillY();
    if (!(amount > 0)) { out.innerHTML = '<p class="fine">Enter an amount above $0.</p>'; return; }
    if (a === null) { out.innerHTML = ""; return; }
    function trio(y, cls, label) {
      var yr = amount * y / 100;
      return '<div class="co ' + cls + '"><p class="co-l">' + label + ' <span class="num">' + f1(y) + "%</span></p>" +
        '<dl class="co-n"><div><dt>Per day</dt><dd class="num">' + money(yr / 365) + "</dd></div>" +
        '<div><dt>Per month</dt><dd class="num">' + money(yr / 12) + "</dd></div>" +
        '<div><dt>Per year</dt><dd class="num">' + money(yr) + "</dd></div></dl></div>";
    }
    out.innerHTML = trio(a, "dc", "Digital credit") + (tb !== null ? trio(tb, "tb", "T-bill") : "");
    $("#calc-note").textContent = "Digital credit uses " + f1(a) + "%, the average of today's yields on " + leadNames() +
      ". T-bill is the 4-week rate. At today's rates, simple interest, before tax. Prices move and issuers set the rates.";
  }
  function fromSlide() { $("#in-amount").value = n(+$("#in-slide").value, 0); renderCalc(); }
  function fromInput() {
    var x = parseNum($("#in-amount").value);
    if (x > 0) $("#in-slide").value = Math.min(250000, Math.max(1000, x));
    renderCalc();
  }

  // ---------- 7. example exchange, from the compare tool ----------
  function renderChat() {
    var res = compare(feed, 8000, 90, 30, ["money_market", "preferred", "tbill"]);
    var rows = res.options.filter(function (o) { return LEAD.indexOf(o.ticker) >= 0; });
    var tb = res.benchmarks.filter(function (b) { return b.id === "tbill_4w"; })[0];
    if (!rows.length) { $(".talk").hidden = true; return; }
    var newer = rows.filter(function (o) { return o.flags.indexOf("short_history") >= 0; }).map(function (o) { return o.ticker; });
    function line(name, y, inc, dc) {
      return '<li class="' + (dc ? "dc" : "") + '"><span>' + esc(name) + '</span><span class="num">' + f1(y) + '%</span><span class="num">' + usd(inc) + "</span></li>";
    }
    $("#chat-bot").innerHTML = "<p>Over 90 days at today's rates, before tax:</p>" +
      '<ul class="ans">' + rows.map(function (o) { return line(o.ticker, o.yield_pct, o.est_income_usd, true); }).join("") +
      (tb && tb.yield_pct !== null ? line("4-week T-bill", tb.yield_pct, tb.est_income_usd, false) : "") + "</ul>" +
      "<p>All three pay a dividend every business day and trade every market day. Prices move and the issuers set the rates" +
      (newer.length ? "; " + newer.join(" and ") + (newer.length > 1 ? " are" : " is") + " newer, with a short record" : "") +
      ". Tell me which, if any, and I'll set up the order for your approval.</p>";
    $("#chat-tag").textContent = "Example from today's data, " + day(res.as_of);
  }

  // ---------- 8. sources ----------
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

  // ---------- setup tabs and copy ----------
  function selectTab(tab, focus) {
    $$('[role="tab"]').forEach(function (t) {
      var on = t === tab;
      t.setAttribute("aria-selected", on ? "true" : "false");
      t.tabIndex = on ? 0 : -1;
      $("#" + t.getAttribute("aria-controls")).hidden = !on;
    });
    $("#copy-msg").textContent = "";
    if (focus) tab.focus();
  }
  function initTabs() {
    var tabs = $$('[role="tab"]');
    tabs.forEach(function (t, i) {
      t.addEventListener("click", function () { selectTab(t, false); });
      t.addEventListener("keydown", function (e) {
        var k = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
        if (k) { e.preventDefault(); selectTab(tabs[(i + k + tabs.length) % tabs.length], true); }
      });
    });
    $$(".pane .copy").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var code = btn.parentNode.querySelector("code"), msg = $("#copy-msg");
        function blocked() {
          var r = document.createRange(); r.selectNodeContents(code);
          var s = window.getSelection(); s.removeAllRanges(); s.addRange(r);
          msg.textContent = "This browser blocked copying. The text is selected: press Ctrl+C or Cmd+C.";
        }
        if (!navigator.clipboard || !window.isSecureContext) return blocked();
        navigator.clipboard.writeText(code.textContent).then(function () {
          btn.textContent = "Copied"; msg.textContent = "";
          setTimeout(function () { btn.textContent = "Copy"; }, 1800);
        }, blocked);
      });
    });
  }

  // ---------- type option switch ----------
  function initTypeSwitch() {
    var cur = document.documentElement.getAttribute("data-type");
    $$(".typesw button").forEach(function (b) {
      b.setAttribute("aria-pressed", b.getAttribute("data-t") === cur ? "true" : "false");
      b.addEventListener("click", function () {
        var t = b.getAttribute("data-t");
        try { localStorage.setItem("dp-type", t); } catch (e) {}
        try { var u = new URL(location.href); u.searchParams.set("type", t); history.replaceState(null, "", u); } catch (e) {}
        document.documentElement.setAttribute("data-type", t);
        var f = $("#fonts"); if (f && window.DP_FONTS) f.href = "https://fonts.googleapis.com/css2?" + window.DP_FONTS[t] + "&display=swap";
        $$(".typesw button").forEach(function (x) { x.setAttribute("aria-pressed", x === b ? "true" : "false"); });
        if (feed) setTimeout(function () { drawEarn(false); drawPaid(); }, 300);
      });
    });
  }

  // ---------- colour option switch ----------
  function initColorSwitch() {
    var cur = document.documentElement.getAttribute("data-color");
    $$(".colorsw button").forEach(function (b) {
      b.setAttribute("aria-pressed", b.getAttribute("data-c") === cur ? "true" : "false");
      b.addEventListener("click", function () {
        var c = b.getAttribute("data-c");
        try { localStorage.setItem("dp-color", c); } catch (e) {}
        try { var u = new URL(location.href); u.searchParams.set("color", c); history.replaceState(null, "", u); } catch (e) {}
        document.documentElement.setAttribute("data-color", c);
        $$(".colorsw button").forEach(function (x) { x.setAttribute("aria-pressed", x === b ? "true" : "false"); });
        drawHeroDither(); drawEdgeDither();
        if (feed) drawEarn(false);
      });
    });
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
    renderHero(); drawEarn(true); renderPanels(); drawPaid(); renderLift(); renderBacked(); renderCalc(); renderChat(); renderSources();
    $("#in-amount").addEventListener("input", fromInput);
    $("#in-slide").addEventListener("input", fromSlide);
    $("#f-calc").addEventListener("submit", function (e) { e.preventDefault(); });
    var w = window.innerWidth, t;
    window.addEventListener("resize", function () {
      if (window.innerWidth === w) return; w = window.innerWidth;
      clearTimeout(t); t = setTimeout(function () { drawEarn(false); drawPaid(); drawHeroDither(); drawEdgeDither(); }, 120);
    });
  }

  initTabs(); initTypeSwitch(); initColorSwitch(); drawHeroDither(); drawEdgeDither();
  load("../v1/").catch(function () { return load("./v1-sample/"); }).then(start).catch(function (e) {
    $("#asof").innerHTML = '<span class="err">The feed did not load (' + esc(e.message) + "). Read the JSON files directly.</span>";
  });
})();
