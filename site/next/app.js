/* DATproof home page. Reads the daily feed at runtime; facts and arithmetic only. */
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
  var FLAG_TEXT = {
    price_moves: "price moves daily", issuer_sets_rate: "issuer sets the rate", short_history: "short price history",
    thin_trading: "thin trading for this amount", payment_gap: "missed a payment", no_payment_in_window: "no payment due in these days",
    stale: "a number is stale", not_bank_insured: "not FDIC insured", smart_contract_risk: "smart-contract risk"
  };
  var BENCH = {
    tbill_4w: ["T-bill", "4 weeks · US Treasury"],
    mmf_vmfxx: ["VMFXX", "Money market fund · Vanguard"],
    usdc_aave_v3: ["USDC lending", "Aave v3 on Ethereum"]
  };
  var SCHEDULE = { "every business day": "daily", "twice a month": "twice a month", monthly: "monthly", quarterly: "quarterly" };
  var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  var MINUS = "−";

  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
  function day(iso, year) { if (!iso) return "—"; var p = iso.split("-"); return +p[2] + " " + MONTHS[+p[1] - 1] + (year ? " " + p[0] : ""); }
  function num(x, d) { return Math.abs(x).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d }); }
  function usd(x, d) { return (x < 0 ? MINUS : "") + "$" + num(x, d || 0); }
  function signed(x, d) { return (x > 0 ? "+" : x < 0 ? MINUS : "") + "$" + num(x, d || 0); }
  function pctTxt(x, d) { return x === null || x === undefined ? "—" : num(x, d === undefined ? 2 : d) + "%"; }
  function host(u) { try { return new URL(u).host.replace(/^www\./, ""); } catch (e) { return u || "—"; } }
  function shortName(ins) { return (ins.name || "").replace(new RegExp("^" + (ins.issuer || "") + "\\s+"), ""); }
  function link(u, label) { return u ? '<a href="' + esc(u) + '" rel="noopener">' + esc(label || host(u)) + "</a>" : "—"; }

  function load(base) {
    return Promise.all(["instruments.json", "scenarios.json"].map(function (f) {
      return fetch(base + f, { cache: "no-cache" }).then(function (r) { if (!r.ok) throw new Error(f + " " + r.status); return r.json(); });
    }));
  }

  var feed, scen, current = 365;

  // section 2
  function renderToday() {
    var rows = feed.instruments.map(function (i) { return { t: "i", y: v(i.yield_pct), d: i }; })
      .concat(feed.benchmarks.map(function (b) { return { t: "b", y: v(b.yield_pct), d: b }; }));
    rows.sort(function (a, b) { return (b.y === null ? -1 : b.y) - (a.y === null ? -1 : a.y); });
    var maxDrop = 50;
    var html = rows.map(function (r) {
      var d = r.d;
      if (r.t === "b") {
        var lab = BENCH[d.id] || [d.name, d.kind];
        var risk = benchmarkFlags(d).map(function (f) { return FLAG_TEXT[f] || f; }).join(" · ");
        return '<tr class="bench"><td class="nm"><b>' + esc(lab[0]) + "</b><span>" + esc(lab[1]) + '</span></td><td class="n y">' +
          pctTxt(r.y) + '</td><td class="n dim">—</td><td class="n dim">—</td><td class="brisk"><span class="mut">' + (risk ? esc(risk) : "no daily price") + "</span></td></tr>";
      }
      var close = v(d.close_usd), par = d.par_usd || 100, wd = v(d.worst_drop_pct);
      var diff = close === null ? null : close - par;
      var pay = d.payments || {}, sched = SCHEDULE[d.schedule] || d.schedule || "";
      var short = (d.trading_days || 0) < SHORT_HISTORY_DAYS ? '<span class="mut">' + d.trading_days + " days of prices</span>" : "";
      var yTitle = r.y === null && d.yield_pct && d.yield_pct.reason ? ' title="' + esc(d.yield_pct.reason) + '"' : "";
      return '<tr><td class="nm"><b>' + esc(d.ticker) + "</b><span><i class=\"nmn\">" + esc(shortName(d)) + " · </i>" + esc(d.issuer) + "</span></td>" +
        '<td class="n y"' + yTitle + ">" + pctTxt(r.y) + "</td>" +
        '<td class="n">' + (close === null ? "—" : "$" + num(close, 2)) + '<span class="mut">' +
          (diff === null ? "" : (diff >= 0 ? "+" : MINUS) + num(diff, 2) + " vs par") + "</span></td>" +
        '<td class="n">' + (pay.in_a_row == null ? "—" : pay.in_a_row) + '<span class="mut">' + esc(sched) + "</span></td>" +
        '<td><div class="drop"><span class="v">' + (wd === null ? "—" : MINUS + num(wd, 1) + "%") + "</span>" +
          '<span class="track" aria-hidden="true"><i style="width:' + (wd === null ? 0 : Math.min(100, wd / maxDrop * 100)) + '%"></i></span>' + short + "</div></td></tr>";
    }).join("");
    $("#t-today tbody").innerHTML = html;

    var s = feed.instruments.map(function (i) {
      return "<b>" + esc(i.ticker) + "</b><span>price " + link(i.close_usd.source) +
        " (" + day(i.close_usd.as_of, true) + "), rate " + link(i.stated_rate_pct.source, host(i.stated_rate_pct.source)) +
        (i.stated_rate_pct.as_of ? " (" + day(i.stated_rate_pct.as_of, true) + (i.stated_rate_pct.stale ? ", stale" : "") + ")" : "") +
        ", dividends " + link(i.dividends_source, host(i.dividends_source)) + "</span>";
    }).concat(feed.benchmarks.map(function (b) {
      return "<b>" + esc((BENCH[b.id] || [b.id])[0]) + "</b><span>yield " + link(b.yield_pct.source, host(b.yield_pct.source)) +
        " (" + day(b.yield_pct.as_of, true) + ")</span>";
    }));
    $("#src-today div").innerHTML = s.join("");
  }

  // section 3
  function parse(el) { var t = el.value.replace(/[$,%\s]/g, ""); return t === "" ? NaN : Number(t); }
  function renderTry() {
    var a = parse($("#in-amount")), d = parse($("#in-days")), m = parse($("#in-drop"));
    var bad = [];
    $("#in-amount").parentNode.classList.toggle("bad", !(a > 0)); if (!(a > 0)) bad.push("an amount above $0");
    $("#in-days").parentNode.classList.toggle("bad", !(Number.isInteger(d) && d > 0)); if (!(Number.isInteger(d) && d > 0)) bad.push("whole days above 0");
    $("#in-drop").parentNode.classList.toggle("bad", !(m >= 0)); if (!(m >= 0)) bad.push("a drop of 0% or more");
    if (bad.length) {
      $("#answer").innerHTML = '<span class="err">Enter ' + bad.join(", ") + ".</span>";
      $("#t-try tbody").innerHTML = ""; $("#out").innerHTML = ""; return;
    }
    var r = compare(feed, a, d, m, KINDS);
    var n = r.options.length, total = feed.instruments.length;
    $("#answer").innerHTML = "<b>" + n + " of " + total + "</b> preferred stocks had a worst drop of " + g(m) + "% or less in the past year. " +
      "At today's rates, " + usd(a, a % 1 ? 2 : 0) + " for " + d + (d === 1 ? " day" : " days") + " would earn:";
    var rows = r.options.map(function (o) {
      return '<tr><td class="nm"><b>' + esc(o.ticker) + "</b><span>" + esc(shortName(feed.instruments.find(function (i) { return i.ticker === o.ticker; }))) + '</span></td><td class="n">' +
        pctTxt(o.yield_pct) + '</td><td class="n earn">' + usd(o.est_income_usd, 2) + '</td><td class="n">' + MINUS + num(o.worst_drop_pct, 1) + "%</td>" +
        '<td class="notes">' + o.flags.map(function (f) { return esc(FLAG_TEXT[f] || f); }).join(" · ") + "</td></tr>";
    });
    if (!n) rows.push('<tr><td colspan="5" class="skip">None of the six fit this limit. The benchmarks are below.</td></tr>');
    rows.push('<tr class="gap"><td colspan="5">Benchmarks, always shown</td></tr>');
    r.benchmarks.forEach(function (b) {
      var lab = BENCH[b.id] || [b.name];
      rows.push('<tr class="bench"><td class="nm"><b>' + esc(lab[0]) + "</b><span>" + esc(lab[1] || "") + '</span></td><td class="n">' + pctTxt(b.yield_pct) +
        '</td><td class="n">' + (b.est_income_usd === null ? "—" : usd(b.est_income_usd, 2)) + '</td><td class="n dim">—</td><td class="notes">' +
        b.flags.map(function (f) { return esc(FLAG_TEXT[f] || f); }).join(" · ") + "</td></tr>");
    });
    $("#t-try tbody").innerHTML = rows.join("");
    $("#out").innerHTML = r.excluded.length
      ? "<h3>Left out</h3><ul>" + r.excluded.map(function (e) { return "<li><b>" + esc(e.ticker) + "</b>" + esc(e.reason) + "</li>"; }).join("") + "</ul>"
      : "";
  }

  // section 4
  function strip(row, scale) {
    var W = 240, mid = 96, k = (W - mid - 4) / scale;  // more room on the right for income
    var x = function (val) { return Math.max(2, Math.min(W - 2, mid + val * k)); };
    var inc = row.dividends_usd || 0, px = row.price_change_usd || 0, low = row.lowest ? row.lowest.below_start_usd : 0;
    var px0 = Math.min(x(0), x(px)), pxW = Math.abs(x(px) - x(0));
    return '<div class="strip"><svg viewBox="0 0 ' + W + ' 22" preserveAspectRatio="none" aria-hidden="true">' +
      '<line x1="' + mid + '" y1="0" x2="' + mid + '" y2="22" stroke="var(--rule-2)" stroke-width="1" vector-effect="non-scaling-stroke"/>' +
      '<rect x="' + mid + '" y="4" width="' + (x(inc) - mid) + '" height="5" rx="1" fill="var(--accent)"/>' +
      '<rect x="' + px0 + '" y="13" width="' + Math.max(pxW, 0.5) + '" height="5" rx="1" fill="var(--bar)"/>' +
      (low ? '<line x1="' + x(-low) + '" y1="15.5" x2="' + mid + '" y2="15.5" stroke="var(--ink-3)" stroke-width="1" stroke-dasharray="2 2" vector-effect="non-scaling-stroke"/>' : "") +
      "</svg>" + (low ? '<span class="dot" style="left:' + (x(-low) / W * 100) + '%"></span>' : "") + "</div>";
  }

  function renderPast() {
    var w = scen.lookback.find(function (l) { return l.days === current; }) || scen.lookback[scen.lookback.length - 1];
    var live = w.instruments.filter(function (i) { return !i.skipped; });
    var scale = 1;
    live.forEach(function (i) {
      scale = Math.max(scale, i.dividends_usd || 0, Math.abs(i.price_change_usd || 0), i.lowest ? i.lowest.below_start_usd : 0);
    });
    var html = w.instruments.map(function (i) {
      var ins = feed.instruments.find(function (f) { return f.ticker === i.ticker; }) || {};
      var name = '<td class="nm"><b>' + esc(i.ticker) + "</b><span>" + esc(shortName({ name: i.name, issuer: ins.issuer })) + "</span></td>";
      if (i.skipped) {
        var m = /start (\d{4}-\d{2}-\d{2})/.exec(i.reason || "");
        return "<tr>" + name + '<td colspan="5" class="skip" title="' + esc(i.reason) + '">Not enough history for ' + w.days + " days" +
          (m ? ": prices start " + day(m[1], true) : "") + ".</td></tr>";
      }
      return "<tr>" + name +
        '<td class="n">' + signed(i.dividends_usd) + '<span class="mut">' + i.dividends_paid + " paid</span></td>" +
        '<td class="n' + (i.price_change_usd < 0 ? " neg" : "") + '">' + signed(i.price_change_usd) + "</td>" +
        '<td class="n"><b>' + signed(i.total_usd) + '</b><span class="mut">' + (i.total_pct > 0 ? "+" : i.total_pct < 0 ? MINUS : "") + num(i.total_pct, 1) + "%</span></td>" +
        '<td class="n">' + (i.lowest ? usd(-i.lowest.below_start_usd) + '<span class="mut">' + day(i.lowest.date, true) + "</span>" : "—") + "</td>" +
        '<td class="viz-cell">' + strip(i, scale) + "</td></tr>";
    }).join("");
    html += '<tr class="gap"><td colspan="6">Benchmarks, at today\'s rate for the whole window</td></tr>';
    html += w.benchmarks.map(function (b) {
      var lab = BENCH[b.id] || [b.name, ""];
      return '<tr class="bench"><td class="nm"><b>' + esc(lab[0]) + "</b><span>" + esc(lab[1]) + '</span></td>' +
        '<td class="n">' + signed(b.total_usd) + '<span class="mut">interest</span></td><td class="n dim">—</td>' +
        '<td class="n">' + signed(b.total_usd) + '<span class="mut">+' + num(b.total_pct, 1) + '%</span></td><td class="n dim">—</td>' +
        '<td><span class="mut">no daily history</span></td></tr>';
    }).join("");
    $("#t-past tbody").innerHTML = html;
    $("#src-past div").innerHTML = live.map(function (i) {
      return "<b>" + esc(i.ticker) + "</b><span>closes " + day(i.start_date, true) + " to " + day(i.end_date, true) + ", " +
        link(i.source, host(i.source)) + "; dividends " + link(i.dividends_source, host(i.dividends_source)) + "</span>";
    }).join("") + '<b>Note</b><span>' + esc(scen.note) + "</span>";
  }

  function renderSeg() {
    var seg = $("#seg");
    seg.innerHTML = scen.lookback.map(function (l) {
      return '<button type="button" role="radio" aria-checked="' + (l.days === current) + '" data-d="' + l.days + '">' + l.days + " days</button>";
    }).join("");
    seg.onclick = function (e) {
      var b = e.target.closest("button"); if (!b) return;
      current = +b.dataset.d; renderSeg(); renderPast();
      seg.querySelector('[aria-checked="true"]').focus();
    };
    seg.onkeydown = function (e) {
      if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
      var ds = scen.lookback.map(function (l) { return l.days; }), i = ds.indexOf(current);
      current = ds[(i + (e.key === "ArrowRight" ? 1 : ds.length - 1)) % ds.length];
      renderSeg(); renderPast(); seg.querySelector('[aria-checked="true"]').focus(); e.preventDefault();
    };
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

  function start(data) {
    feed = data[0]; scen = data[1];
    var px = feed.instruments.map(function (i) { return i.close_usd && i.close_usd.as_of; }).filter(Boolean).sort().pop();
    $("#date").innerHTML = "Data for <b>" + day(feed.date, true) + "</b>" + (px && px !== feed.date ? " · closing prices from " + day(px, true) : "");
    renderToday(); renderTry(); renderSeg(); renderPast();
    ["#in-amount", "#in-days", "#in-drop"].forEach(function (s) { $(s).addEventListener("input", renderTry); });
    $("#f-try").addEventListener("submit", function (e) { e.preventDefault(); });
  }

  $("#copy").addEventListener("click", copy);
  load("../v1/").catch(function () { return load("./v1-sample/"); }).then(start).catch(function (e) {
    $("#date").innerHTML = '<span class="err">The feed did not load (' + esc(e.message) + "). Try again later, or read the JSON files directly.</span>";
  });
})();
