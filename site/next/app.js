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
    var ahead = res.filter(function (r) { return r > 0; }).length;
    return [{ days: days, holds: n, bought_from: hs[0][1], bought_to: hs[n - 1][1],
      closes_from: String(rows[0][0]).slice(0, 10),
      tbill_pct: tb, tbill_hold_pct: hurdle === null ? null : round(hurdle, 3),
      beat_tbill: beat, beat_tbill_pct: beat === null ? null : share(beat, n),
      lost: lost, lost_pct: share(lost, n), ahead: ahead, ahead_pct: share(ahead, n),
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

  // ---------- dithered shading ----------
  // One ink system for green and blue: an 8x8 ordered (Bayer) dot pattern thresholded against a continuous
  // tone, so every cell picks its own level (64 of them) and nothing steps in visible blocks.
  // Dots mean digital credit; T-bills and cash stay flat grey. Orange stays flat.
  // Canvas draws it; without canvas the static SVG patterns below are the fallback.
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
  // Static fallbacks (no canvas): banded SVG versions of the backdrop, the section edge and the bars.
  function svgHeroDither(W) {
    var R = Math.round(Math.min(W * 0.55, 780)), N = 12;
    var svg = el("svg", { class: "dz dz-hero", width: W, height: R, viewBox: "0 0 " + W + " " + R, "aria-hidden": "true", focusable: "false" });
    ditherDefs(svg, "dzh", "dz-ink");
    for (var b = 0; b < N; b++) svg.appendChild(el("circle", { cx: W, cy: 0, r: Math.round(R * (1 - b / N)), fill: "url(#dzh" + (1 + Math.round(b * 9 / (N - 1))) + ")" }));
    return svg;
  }
  function svgEdgeDither(W) {
    var H = 48, rows = 12;
    var svg = el("svg", { class: "dz dz-edge", width: W, height: H, viewBox: "0 0 " + W + " " + H, preserveAspectRatio: "none", "aria-hidden": "true", focusable: "false" });
    ditherDefs(svg, "dze", "dz-ink");
    for (var r = 0; r < rows; r++) svg.appendChild(el("rect", { x: 0, y: r * H / rows, width: W, height: H / rows, fill: "url(#dze" + Math.max(1, Math.round(10 - r * 10 / rows)) + ")" }));
    return svg;
  }
  function ditherBar(x0, y, w, h) {
    var g = el("g", { class: "c-bar dc dz-bar" }), LV = [2, 4, 8, 12, 16], N = LV.length;
    for (var s = 0; s < N; s++) {
      var a = Math.round(x0 + w * s / N), b = Math.round(x0 + w * (s + 1) / N);
      g.appendChild(el("rect", { x: a, y: y, width: b - a, height: h, fill: "url(#dzc" + LV[s] + ")" }));
    }
    return g;
  }

  var DZ = (function () {
    var probe = document.createElement("canvas"), ok = false;
    try { ok = !!(probe.getContext && probe.getContext("2d") && window.ImageData && window.Uint32Array); } catch (e) {}
    var mq = window.matchMedia ? window.matchMedia("(prefers-reduced-motion: reduce)") : null;
    function still() { return !!(mq && mq.matches); }

    // 8x8 Bayer thresholds in (0, 1), built from the 2x2 rule M' = [[4M, 4M+2], [4M+3, 4M+1]].
    var M = [0], s = 1;
    while (s < 8) {
      var nm = [];
      for (var y = 0; y < s * 2; y++) for (var x = 0; x < s * 2; x++) {
        var b = M[(y % s) * s + (x % s)] * 4;
        nm[y * s * 2 + x] = b + [0, 2, 3, 1][(y >= s ? 2 : 0) + (x >= s ? 1 : 0)];
      }
      M = nm; s *= 2;
    }
    var TH = new Float32Array(64);
    for (var q = 0; q < 64; q++) TH[q] = (M[q] + 0.5) / 64;
    // Near empty and near solid the ordered pattern reads as a lattice (a visible edge). There, and only
    // there, each cell's threshold leans toward a fixed per-cell random value so the fringe scatters.
    var JT = new Float32Array(4096);
    function th(cx, cy, v, J) {
      var t = TH[(cy & 7) * 8 + (cx & 7)], f = v > 1 ? v - 1 : v, m = f < 0.5 ? f : 1 - f;
      if (m >= 0.32) return t;
      var k = m / 0.32, j = J * (1 - k * k * (3 - 2 * k));
      return t + (JT[(cy & 63) * 64 + (cx & 63)] - t) * j;
    }

    // Cell size: a whole number of device pixels (crisp), about 1.5 CSS px on retina and 2 px at 1x.
    function grid() {
      var d = Math.min(window.devicePixelRatio || 1, 3);
      var dev = d >= 1.75 ? Math.round(1.5 * d) : Math.max(1, Math.round(2 * d));
      return { dpr: d, dev: dev, css: dev / d };
    }

    // CSS colour -> packed RGBA (little-endian ImageData word). Canvas resolves oklch for us.
    var pc = document.createElement("canvas"); pc.width = pc.height = 1;
    var px = ok ? pc.getContext("2d", { willReadFrequently: true }) : null;
    function rgba(css) {
      px.clearRect(0, 0, 1, 1); px.fillStyle = "rgba(0,0,0,0)"; px.fillStyle = css; px.fillRect(0, 0, 1, 1);
      var d = px.getImageData(0, 0, 1, 1).data; return [d[0], d[1], d[2], d[3]];
    }
    function pack(c) { return ((c[3] << 24) | (c[2] << 16) | (c[1] << 8) | c[0]) >>> 0; }
    function mix(a, b, t) { return [0, 1, 2, 3].map(function (i) { return Math.round(a[i] + (b[i] - a[i]) * t); }); }
    function inks() {
      var cs = getComputedStyle(document.documentElement);
      var dz = rgba(cs.getPropertyValue("--dither").trim()), ac = rgba(cs.getPropertyValue("--accent").trim());
      return { dim: pack(dz), mid: pack(mix(dz, ac, 0.38)), acc: pack(ac) };
    }

    // Smooth value noise, two octaves moving in different directions so the field changes shape, not position.
    function hash(i, j) {
      var h = Math.imul(i, 374761393) ^ Math.imul(j, 668265263);
      h = Math.imul(h ^ (h >>> 13), 1274126177);
      return ((h ^ (h >>> 16)) >>> 0) / 4294967296;
    }
    function vn(x, y) {
      var i = Math.floor(x), j = Math.floor(y), fx = x - i, fy = y - j;
      var ux = fx * fx * (3 - 2 * fx), uy = fy * fy * (3 - 2 * fy);
      var a = hash(i, j), b = hash(i + 1, j), c = hash(i, j + 1), d = hash(i + 1, j + 1);
      return a + (b - a) * ux + (c - a) * uy + (a - b - c + d) * ux * uy;
    }
    // Each octave is turned off the screen axes so the noise lattice never lines up into straight seams.
    function weather(x, y, t, sc) {
      var a = (0.866 * x + 0.5 * y) / sc, b = (-0.5 * x + 0.866 * y) / sc;
      var c = (0.643 * x - 0.766 * y) / (sc * 0.55), d = (0.766 * x + 0.643 * y) / (sc * 0.55);
      return 0.62 * vn(a + t * 0.034, b - t * 0.013) + 0.38 * vn(c - t * 0.05 + 5.2, d + t * 0.021 + 1.3);
    }
    for (var jq = 0; jq < 4096; jq++) JT[jq] = hash(jq & 63, (jq >> 6) + 977);
    function sm(a, b, x) { var t = Math.min(1, Math.max(0, (x - a) / (b - a))); return t * t * (3 - 2 * t); }

    // ---- live fields: canvas at one pixel per cell, scaled up pixel-exact by CSS ----
    var layers = [], raf = 0, STEP = 1000 / 15, T0 = 0;
    var io = window.IntersectionObserver ? new IntersectionObserver(function (es) {
      es.forEach(function (e) { if (e.target._dz) e.target._dz.on = e.isIntersecting; });
      wake();
    }) : null;
    function tick(now) {
      raf = 0;
      if (document.hidden || still()) return;
      if (!T0) T0 = now;
      var any = false;
      layers.forEach(function (L) {
        if (!L.on || !L.cv.isConnected) return;
        any = true;
        if (now - L.last >= STEP) { L.last = now; paintField(L, (now - T0) / 1000 + 40); }
      });
      if (any) raf = requestAnimationFrame(tick);
    }
    function wake() { if (!raf && !document.hidden && !still()) raf = requestAnimationFrame(tick); }
    document.addEventListener("visibilitychange", wake);
    if (mq && mq.addEventListener) mq.addEventListener("change", function () { layers.forEach(function (L) { paintField(L, 40); }); wake(); });

    function paintField(L, t) {
      var cw = L.cw, ch = L.ch, K = 4, gw = Math.ceil(cw / K) + 2, gh = Math.ceil(ch / K) + 2, c = L.cell;
      if (!L.g || L.g.length !== gw * gh) L.g = new Float32Array(gw * gh);
      var g = L.g, buf = L.buf, i1 = L.ink.dim, i2 = L.ink.mid;
      for (var gy = 0; gy < gh; gy++) for (var gx = 0; gx < gw; gx++) g[gy * gw + gx] = L.field(gx * K * c, gy * K * c, t);
      for (var y = 0; y < ch; y++) {
        var gy0 = (y / K) | 0, fy = (y - gy0 * K) / K, r0 = gy0 * gw, r1 = r0 + gw, row = y * cw;
        for (var x = 0; x < cw; x++) {
          var gx0 = (x / K) | 0, fx = (x - gx0 * K) / K;
          var a = g[r0 + gx0], b = g[r0 + gx0 + 1], cc = g[r1 + gx0], d = g[r1 + gx0 + 1];
          var v = (a + (b - a) * fx) * (1 - fy) + (cc + (d - cc) * fx) * fy;
          if (v <= 0.0005) { buf[row + x] = 0; continue; }
          var t = th(x, y, v, 0.72);
          buf[row + x] = v - 1 > t ? i2 : v > t ? i1 : 0;
        }
      }
      L.ctx.putImageData(L.img, 0, 0);
    }
    function field(cls, cssW, cssH, fn, place) {
      var G = grid(), cw = Math.max(1, Math.ceil(cssW / G.css)), ch = Math.max(1, Math.ceil(cssH / G.css));
      var cv = document.createElement("canvas");
      cv.className = "dz dz-cv " + cls; cv.setAttribute("aria-hidden", "true");
      cv.width = cw; cv.height = ch;
      cv.style.width = cw * G.css + "px"; cv.style.height = ch * G.css + "px";
      var ctx = cv.getContext("2d"), img = ctx.createImageData(cw, ch);
      var L = { cv: cv, ctx: ctx, img: img, buf: new Uint32Array(img.data.buffer), cw: cw, ch: ch, cell: G.css, field: fn, ink: inks(), on: !io, last: 0 };
      cv._dz = L;
      place(cv);
      paintField(L, 40);
      layers = layers.filter(function (x) { return x.cv.isConnected; });
      layers.push(L);
      if (io) io.observe(cv);
      wake();
      return cv;
    }

    // Backdrop behind the first screen: a tone that falls off from beyond the top-right corner, never
    // reaching the headline or the chart, broken up by slow weather.
    function hero(W) {
      var phone = W < 640, R = phone ? W * 0.78 : Math.min(W * 0.6, 900);
      var cx = W + R * (phone ? 0.2 : 0.06), cy = -R * (phone ? 0.24 : 0.1), left = Math.max(0, Math.floor(cx - R)), H = Math.ceil(cy + R);
      return field("dz-hero", W - left, H, function (x, y, t) {
        var X = x + left, dx = (X - cx) / R, dy = (y - cy) / R, d = Math.sqrt(dx * dx + dy * dy);
        if (d >= 1) return 0;
        var base = Math.pow(1 - sm(0.04, 1, d), 1.5), w = weather(X, y, t, 260);
        return base * (0.3 + 1.05 * w);
      }, function (cv) { cv.style.left = "auto"; cv.style.right = "0"; document.body.insertBefore(cv, document.body.firstChild); });  // pinned right: the canvas rounds up to whole cells and must not widen the page
    }
    // Section edge: a soft band of dots, no straight line on either side, thinning at the screen edges.
    function edge(sec, W) {
      var H = 88;
      return field("dz-edge", W, H, function (x, y, t) {
        var h = y / H, w = weather(x, y * 2, t * 0.8, 230), w2 = weather(x + 900, 40, t * 0.5, 420);
        var c = 0.28 + 0.3 * w2, sp = 0.1 + 0.16 * w, z = (h - c) / sp;
        var prof = Math.exp(-z * z) * sm(0, 0.18, h) * (1 - sm(0.8, 1, h));
        var ends = sm(0, 0.2, x / W) * sm(0, 0.2, 1 - x / W);
        return prof * ends * (0.06 + 0.78 * w * w);
      }, function (cv) { sec.insertBefore(cv, sec.firstChild); });
    }

    // ---- figure ink: device-pixel canvas behind a chart, dots snapped to one shared grid ----
    function sheet(host, cssW, cssH, cls) {
      var G = grid(), cv = host.querySelector(":scope > canvas.dz-ov");
      if (!cv) { cv = document.createElement("canvas"); cv.className = "dz dz-ov " + (cls || ""); cv.setAttribute("aria-hidden", "true"); host.insertBefore(cv, host.firstChild); }
      var w = Math.max(1, Math.round(cssW * G.dpr)), h = Math.max(1, Math.round(cssH * G.dpr));
      if (cv.width !== w || cv.height !== h) { cv.width = w; cv.height = h; }
      cv.style.width = cssW + "px"; cv.style.height = cssH + "px";
      var ctx = cv.getContext("2d"), img = ctx.createImageData(w, h);
      host.classList.add("dz-host");
      return { cv: cv, ctx: ctx, img: img, buf: new Uint32Array(img.data.buffer), w: w, h: h, G: G, ink: inks() };
    }
    // Fill a CSS-px rectangle with dots; tone(xCss, yCss) is read once per cell. Two inks: dim then bright.
    function fill(S, x0, y0, x1, y1, tone, lo, hi, J) {
      if (J === undefined) J = 0.3;
      var G = S.G, dev = G.dev, dpr = G.dpr, buf = S.buf, W = S.w;
      var X0 = Math.max(0, Math.round(x0 * dpr)), X1 = Math.min(W, Math.round(x1 * dpr));
      var Y0 = Math.max(0, Math.round(y0 * dpr)), Y1 = Math.min(S.h, Math.round(y1 * dpr));
      for (var cy = (Y0 / dev) | 0; cy * dev < Y1; cy++) {
        var py0 = Math.max(Y0, cy * dev), py1 = Math.min(Y1, cy * dev + dev), ty = (cy + 0.5) * G.css;
        for (var cx = (X0 / dev) | 0; cx * dev < X1; cx++) {
          var v = tone((cx + 0.5) * G.css, ty), t = v > 0.0005 ? th(cx, cy, v, J) : 2;
          var c = v - 1 > t ? hi : v > t ? lo : 0;
          if (!c) continue;
          var px0 = Math.max(X0, cx * dev), px1 = Math.min(X1, cx * dev + dev);
          for (var py = py0; py < py1; py++) for (var p = py * W + px0, e = py * W + px1; p < e; p++) buf[p] = c;
        }
      }
    }
    function done(S) { S.ctx.putImageData(S.img, 0, 0); }

    // Income bars: sparse dots at the start, solid at the value. Grows and resolves once on first view.
    function bars(box, W, H, list, animate) {
      var S = sheet(box, W, H);
      function frame(p) {
        S.buf.fill(0);
        list.forEach(function (r, k) {
          var e = Math.min(1, Math.max(0, (p - k * 0.07) / 0.86));
          var grow = 1 - Math.pow(1 - e, 4), res = e * e * (3 - 2 * e);
          var w = Math.max(2, r.w * (0.015 + 0.985 * grow)), x0 = r.x;
          fill(S, x0, r.y, x0 + w, r.y + r.h, function (x) {
            var u = (x - x0) / w, base = 0.2 + 0.8 * Math.pow(sm(0, 0.94, u), 1.5);
            return base * (0.16 + 0.84 * res);
          }, S.ink.acc, S.ink.acc);
        });
        done(S);
      }
      box.classList.add("dz-live");
      if (!animate || still() || document.hidden) { frame(1); return; }
      var t0 = 0, fin = false, D = 1500;
      function finish() { if (!fin) { fin = true; frame(1); } }
      function step(now) {
        if (fin || !S.cv.isConnected) return;
        if (document.hidden) return finish();
        if (!t0) t0 = now;
        var p = Math.min(1, (now - t0) / D);
        frame(p);
        if (p < 1) requestAnimationFrame(step); else fin = true;
      }
      frame(1);  // fully drawn until the moment actually starts
      function go() { requestAnimationFrame(function (now) { if (!fin) { frame(0); requestAnimationFrame(step); } }); setTimeout(finish, D + 2500); }
      var r0 = box.getBoundingClientRect();
      if (r0.top < window.innerHeight && r0.bottom > 0) return go();
      if (!io) return;
      var o = new IntersectionObserver(function (es) {
        if (es.some(function (e) { return e.intersectionRatio > 0.35; })) { o.disconnect(); go(); }
      }, { threshold: [0.35] });
      o.observe(box);
    }
    // Area under a price line: dense just under the line, thinning to nothing well above the floor.
    function area(box, W, H, pts, floor) {
      var S = sheet(box, W, H), n = pts.length, x0 = pts[0][0], x1 = pts[n - 1][0], j = 0;
      var colY = new Float32Array(Math.ceil(W) + 2);
      for (var cx = 0; cx < colY.length; cx++) {
        while (j < n - 2 && pts[j + 1][0] < cx) j++;
        var a = pts[j], b = pts[j + 1], u = b[0] === a[0] ? 0 : (cx - a[0]) / (b[0] - a[0]);
        colY[cx] = a[1] + (b[1] - a[1]) * Math.min(1, Math.max(0, u));
      }
      var top = Math.min.apply(null, pts.map(function (p) { return p[1]; }));
      fill(S, x0, top, x1, floor, function (x, y) {
        var ly = colY[Math.max(0, Math.min(colY.length - 1, Math.round(x)))], dd = y - ly - 1.5;
        if (dd < 0) return 0;
        var depth = Math.max(36, (floor - ly) * 0.8);
        var ends = sm(0, 18, x - x0) * sm(0, 18, x1 - x);
        return 0.78 * Math.pow(1 - sm(0, depth, dd), 1.8) * ends;
      }, S.ink.dim, S.ink.dim, 0.6);
      done(S);
    }
    // Strip fill (risk figure, estimator): from sparse at the left to solid by `solidFrom` (0-1).
    function strip(host, solidFrom) {
      var W = host.clientWidth, H = host.clientHeight;
      if (!W || !H) return;
      var S = sheet(host, W, H);
      fill(S, 0, 0, W, H, function (x) { return 0.2 + 0.8 * Math.pow(sm(0, solidFrom * W, x), 1.5); }, S.ink.acc, S.ink.acc);
      done(S);
      host.classList.add("dz-live");
    }
    function clear(host) {
      var cv = host && host.querySelector(":scope > canvas.dz-ov");
      if (cv) host.removeChild(cv);
      if (host) host.classList.remove("dz-live", "dz-host");
    }
    return { ok: ok, still: still, hero: hero, edge: edge, bars: bars, area: area, strip: strip, clear: clear };
  })();

  // Backdrop behind the first screen.
  function drawHeroDither() {
    $$(".dz-hero").forEach(function (o) { o.parentNode.removeChild(o); });
    if (!dithered()) return;
    var W = document.documentElement.clientWidth;
    if (DZ.ok) DZ.hero(W);
    else document.body.insertBefore(svgHeroDither(W), document.body.firstChild);
  }
  // Soft dot horizons at the top of "Estimate your income" and "Connect your agent".
  function drawEdgeDither() {
    ["#calc", "#agent"].forEach(function (id) {
      var sec = $(id); if (!sec) return;
      var old = sec.querySelector(".dz-edge"); if (old) sec.removeChild(old);
      if (!dithered()) return;
      var W = document.documentElement.clientWidth;
      if (DZ.ok) DZ.edge(sec, W);
      else if (id === "#agent") sec.insertBefore(svgEdgeDither(W), sec.firstChild);
    });
  }
  // Risk figure: the idle cash that earns is drawn in dots, solid where its label sits.
  function inkLift() {
    var seg = $(".lf-row.dc .lf-seg.cash");
    if (!seg) return;
    if (!DZ.ok || !dithered()) return DZ.clear(seg);
    seg.classList.add("dz-live");  // label moves to the solid end before measuring
    var lab = seg.firstElementChild, W = seg.clientWidth, lw = lab ? lab.offsetWidth + 24 : 0;
    DZ.strip(seg, Math.max(0.35, Math.min(0.92, (W - lw) / W)));
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
    var foot = [];
    foot.push("A year at today's rates and yields, before tax; price change left out.");
    $("#earn-foot").textContent = foot.join(" ");
  }

  function rateOf(id) {
    var r = ((feed.comparison_rates || {}).rates || []).filter(function (x) { return x.id === id; })[0];
    return r && has(r.yield_pct) ? v(r.yield_pct) : null;
  }
  function earnRows() {
    var rows = [], hys = rateOf("hys_top"), tb = tbillY();
    if (hys !== null) rows.push({ name: "High-yield savings", note: "at today's rate", usd: AMOUNT * hys / 100 });
    if (tb !== null) rows.push({ name: "T-bill", note: "4-week, at today's rate", usd: AMOUNT * tb / 100 });
    lead().forEach(function (i) {
      rows.push({ name: i.ticker, note: "at today's yield", usd: AMOUNT * v(i.yield_pct) / 100, dc: true });
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
    var infUsd = inf ? AMOUNT * v(inf) / 100 : null, dz = dithered(), inkBars = [];
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
      if (r.dc && dz) { svg.appendChild(ditherBar(L, by, Math.max(2, x(r.usd) - L), bh)); inkBars.push({ x: L, y: by, w: Math.max(2, x(r.usd) - L), h: bh }); }
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
    var keep = box.querySelector(":scope > canvas.dz-ov");
    box.innerHTML = "";
    if (keep) box.appendChild(keep);
    box.appendChild(svg);
    if (DZ.ok && inkBars.length) DZ.bars(box, W, H, inkBars, first); else DZ.clear(box);
    box.setAttribute("aria-label", "Annual income on $10,000 of idle cash: " + rows.map(function (r) { return r.name + " " + usd(r.usd) + " (" + r.note + ")"; }).join("; ") +
      (infUsd !== null ? ". Inflation: " + usd(infUsd) + "." : "."));
    if (first) box.classList.add("draw");
  }

  // ---------- 2. the three ----------
  // ---------- 3. liquid and steady ----------
  function nearShare(rows) { return rows.filter(function (r) { return Math.abs(r[1] - 100) <= 5; }).length / rows.length; }

  function drawPaid() {
    var wrap = $("#paid-charts"), out = [];
    LEAD.forEach(function (t) {
      var i = inst(t), c = closes[t];
      if (!i || !c || !c.rows || c.rows.length < 20) return;
      out.push({ i: i, rows: c.rows, divs: (c.dividends || []) });
    });
    if (!out.length) { $("#paid").hidden = true; return; }
    if (!wrap.children.length) {
      wrap.innerHTML = out.map(function (o) {
        return '<div class="pc"><h3>' + esc(o.i.ticker) + '</h3><div class="chart" role="img"></div></div>';
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
      // The $95 to $105 band only for issues whose issuer states it aims to keep the price near $100.
      if ((o.i.by_buy_price || {}).issuer_aims_price_near_100) svg.appendChild(el("rect", { x: ml, y: Y(105), width: W - ml - mr, height: Y(95) - Y(105), class: "c-band" }));
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
      var keep = box.querySelector(":scope > canvas.dz-ov");
      box.innerHTML = ""; if (keep) box.appendChild(keep); box.appendChild(svg);
      if (DZ.ok && dithered()) DZ.area(box, W, H, rows.map(function (r) { return [X(r[0]), Y(r[1])]; }), mt + ph); else DZ.clear(box);
      var share = Math.round(nearShare(rows) * 100);
      box.setAttribute("aria-label", o.i.ticker + " closing price over the past year, each dividend paid marked below. Within $5 of $100 on " + share + "% of days. " + usd(last[1], 2) + " at the last close.");
    });
  }


  // ---------- 3b. odds by holding time ----------
  // ---------- 4. better risk-adjusted returns ----------
  // ---------- 5. backed by bitcoin and cash: written into the HTML by datproof_feed/pages.py ----------

  // ---------- 6. calculator ----------
  function parseNum(s) { var x = Number(String(s).replace(/[$,\s]/g, "")); return isFinite(x) ? x : NaN; }
  // Your situation: the same arithmetic as compare.situation in the feed code, from published figures only.
  var HOLDS = { "1 month": 30, "3 months": 90, "6 months": 180, "1 year": 365 };
  var HOLD_ADJ = { "1 month": "1-month", "3 months": "3-month", "6 months": "6-month", "1 year": "1-year" };
  function sgn(x) { return (x >= 0 ? "+" : "\u2212") + f1(Math.abs(x)) + "%"; }
  function money2(x) { return (x >= 0 ? "+" : "\u2212") + usd(Math.abs(x), 2); }
  function rateNode(id) { return ((feed.comparison_rates || {}).rates || []).filter(function (x) { return x.id === id; })[0]; }
  function renderSit() {
    var amount = parseNum($("#in-amount").value), hold = $("#in-hold").value, sits = $("#in-sits").value;
    var out = $("#calc-out"), days = HOLDS[hold];
    if (!(amount > 0)) { out.innerHTML = '<p class="fine">Enter an amount above $0.</p>'; return; }
    var rn = rateNode(sits) || {}, rate = has(rn.yield_pct) ? v(rn.yield_pct) : null, label = (rn.label || "").split(",")[0];
    var cash = rate === null ? null : Math.round(amount * rate / 100 * days / 365 * 100) / 100;
    var cols = LEAD.map(inst).filter(function (i) { return !!i; });
    function cell(t, big, small) {
      return '<td data-l="' + esc(t) + '">' + (big ? '<span class="st-n num">' + esc(big) + "</span>" : "") +
        (small ? '<span class="st-s">' + esc(small) + "</span>" : "") + "</td>";
    }
    function row(lbl, f) { return '<tr><th scope="row">' + esc(lbl) + "</th>" + cols.map(function (i) { var c = f(i); return cell(i.ticker, c[0], c[1]); }).join("") + "</tr>"; }
    function div(i) { var y = v(i.yield_pct); return y === null ? null : Math.round(amount * y / 100 * days / 365 * 100) / 100; }
    var body =
      row("Dividends over " + hold, function (i) { var d = div(i); return d === null ? ["not available", ""] : [usd(d, 2), "at " + f1(v(i.yield_pct)) + "% a year today"]; }) +
      row(label + " earns", function () { return cash === null ? ["not available", rn.yield_pct && rn.yield_pct.reason || ""] : [usd(cash, 2), "at " + n(rate, 2) + "%"]; }) +
      row("Difference", function (i) { var d = div(i); return d === null || cash === null ? ["not available", ""] : [money2(Math.round((d - cash) * 100) / 100), ""]; }) +
      row("Past " + HOLD_ADJ[hold] + " holds", function (i) {
        var o = (i.hold_odds || {})[String(days)] || {};
        if (o.reason || o.median_pct == null) return ["", "No record yet" + (o.first_results_around ? "; results begin around " + day(o.first_results_around) : "") + "."];
        return [Math.round(o.ahead_pct) + "%", "came out ahead \u00b7 typical " + sgn(o.median_pct) + " \u00b7 worst " + sgn(o.worst_pct)];
      }) +
      row("Whole shares", function (i) {
        var c = v(i.close_usd); if (c === null) return ["not available", ""];
        var gap = Math.round((c - (i.par_usd || 100)) * 100) / 100;
        return [n(Math.floor(amount / c), 0), "at " + usd(c, 2) + ", " + (gap < 0 ? usd(-gap, 2) + " under $100" : gap > 0 ? usd(gap, 2) + " over $100" : "at $100")];
      }) +
      '<tr class="st-buy"><th scope="row">Where to buy</th>' + cols.map(function (i) { return '<td data-l="' + esc(i.ticker) + '"><a href="#buy">Brokers for ' + esc(i.ticker) + "</a></td>"; }).join("") + "</tr>";
    var head = cols.map(function (i) { return '<th scope="col">' + esc(i.ticker) + '<span class="st-iss">' + esc(i.issuer || "") + "</span></th>"; }).join("");
    out.innerHTML = '<table class="st"><caption class="vh">Your situation: ' + esc(usd(amount)) + " for " + esc(hold) + ", now in " + esc(label.toLowerCase()) +
      '. The same rows for STRC, SATA and SATS</caption><thead><tr><th scope="col"><span class="vh">Row</span></th>' + head + "</tr></thead><tbody>" + body + "</tbody></table>";
    $("#calc-note").textContent = "Dividends at today's yield, before tax, price change left out. Past holds are dividends plus price change. " +
      (rn.label || "") + ": " + (rate === null ? "not available" : n(rate, 2) + "%, " + day(rn.yield_pct.as_of)) + ". What can go wrong is above.";
  }

  // ---------- 7. example exchange, from the compare tool ----------
  // ---------- 8. sources ----------
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

  function getJSON(u) { return fetch(u, { cache: "no-cache" }).then(function (r) { if (!r.ok) throw new Error(u + " " + r.status); return r.json(); }); }
  function load(base) {
    return Promise.all([getJSON(base + "instruments.json"), getJSON(base + "scenarios.json")].concat(
      LEAD.map(function (t) { return getJSON(base + "instrument/" + t + ".json").catch(function () { return null; }); })
    )).then(function (d) {
      // A feed built before inflation, coverage and daily closes were added cannot draw this page.
      if (!("inflation_yoy_pct" in d[0]) || !d[2] || !d[2].closes) throw new Error("older feed format");
      return d;
    });
  }

  function start(d) {
    feed = d[0]; scen = d[1];
    d.slice(2).forEach(function (x) { if (x && x.closes) closes[x.ticker] = { rows: x.closes.rows, dividends: x.dividends }; });
    // Every figure outside the charts and the estimator is written into the HTML by datproof_feed/pages.py.
    // The default case of "your situation" is written into the HTML; the form redraws it only when changed.
    renderHero(); drawEarn(true); drawPaid(); inkLift();
    ["#in-amount", "#in-hold", "#in-sits"].forEach(function (id) { $(id).addEventListener(id === "#in-amount" ? "input" : "change", renderSit); });
    $("#f-calc").addEventListener("submit", function (e) { e.preventDefault(); });
    var w = window.innerWidth, t;
    window.addEventListener("resize", function () {
      if (window.innerWidth === w) return; w = window.innerWidth;
      clearTimeout(t); t = setTimeout(function () { drawEarn(false); drawPaid(); drawHeroDither(); drawEdgeDither(); inkLift(); }, 120);
    });
  }

  initTabs(); drawHeroDither(); drawEdgeDither();
  load("../v1/").catch(function () { return load("./v1-sample/"); }).then(start).catch(function (e) {
    $("#earn-foot").innerHTML = '<span class="err">The charts did not load (' + esc(e.message) + "). The figures on this page are written in; the JSON files have the rest.</span>";
  });
})();
