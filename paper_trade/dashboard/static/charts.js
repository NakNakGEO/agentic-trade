// Live candlestick chart in TradingView's style (their open-source lightweight-charts library), fed by /api/candles.
// The forming candle moves with every TradingView snapshot; both accounts' trades are drawn on top.
(() => {
  const FRAMES = ["1m", "5m", "15m", "1h", "4h", "1D"];
  const PERIOD = { "1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1D": 86400 };
  const GROUPS = { forex: "Forex", gold: "Metals", crypto: "Crypto", stock: "Stocks" };
  const POLL_MS = 4000;
  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const $ = (id) => document.getElementById(id);
  const state = { view: "tv", ticker: decodeURIComponent(location.hash.slice(1)) || null, frame: "1m", key: "", last: 0, lines: [], data: null };

  const chart = LightweightCharts.createChart($("chart"), {
    autoSize: true,
    layout: { background: { color: css("--bg") }, textColor: css("--mute"), fontSize: 12 },
    grid: { vertLines: { color: css("--line") }, horzLines: { color: css("--line") } },
    rightPriceScale: { borderColor: css("--line") },
    timeScale: { borderColor: css("--line"), timeVisible: true, secondsVisible: false, rightOffset: 8 },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
  });
  const series = chart.addCandlestickSeries({
    upColor: css("--up"), downColor: css("--down"), borderVisible: false,
    wickUpColor: css("--up"), wickDownColor: css("--down"),
  });

  const digits = (p) => (p >= 1000 ? 2 : p >= 10 ? 3 : 5);
  const fmt = (p) => (p == null ? "-" : Number(p).toLocaleString("en-US", { minimumFractionDigits: digits(p), maximumFractionDigits: digits(p) }));
  const money = (v) => (v == null ? "-" : `${v >= 0 ? "+" : "-"}$${Math.abs(v).toFixed(2)}`);
  const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };

  function buttons(symbols) {
    const nav = $("symbols");
    nav.replaceChildren();
    let group = null;
    for (const s of symbols) {
      if (s.class !== group) { group = s.class; nav.append(el("span", "grp", GROUPS[group] || group)); }
      const b = el("button", s.ticker === state.ticker ? "on" : "", s.ticker);
      b.onclick = () => { state.ticker = s.ticker; location.hash = s.ticker; select(); };
      nav.append(b);
    }
    const frames = $("frames");
    frames.replaceChildren(...FRAMES.map((f) => {
      const b = el("button", f === state.frame ? "on" : "", f);
      b.onclick = () => { state.frame = f; select(); };
      return b;
    }));
  }

  function setView(view) {
    state.view = view;
    document.body.dataset.view = view;
    document.querySelectorAll("#views button").forEach((b) => b.classList.toggle("on", b.dataset.view === view));
    showTv();
  }

  function showTv() {
    if (state.view === "tv" && state.ticker) import("/static/tvwidget.js").then((m) => m.showTradingView(state.ticker, $("tvbox")));
  }

  function select() {
    showTv();
    document.querySelectorAll("#symbols button").forEach((b) => b.classList.toggle("on", b.textContent === state.ticker));
    document.querySelectorAll("#frames button").forEach((b) => b.classList.toggle("on", b.textContent === state.frame));
    state.key = "";
    load();
  }

  function legend(bar) {
    const box = $("legend");
    box.replaceChildren();
    if (!bar) return;
    for (const [k, v] of [["O", bar.open], ["H", bar.high], ["L", bar.low], ["C", bar.close]]) {
      box.append(el("b", null, k), document.createTextNode(`${fmt(v)}  `));
    }
  }

  function drawPositions(positions) {
    state.lines.forEach((l) => series.removePriceLine(l));
    state.lines = [];
    const line = (price, color, title, style) => state.lines.push(series.createPriceLine({
      price, color, lineWidth: 2, lineStyle: style, axisLabelVisible: true, title }));
    for (const p of positions) {
      const who = p.account.split(" ").pop();
      line(p.entry, css("--entry"), `${who} ${p.side} entry`, LightweightCharts.LineStyle.Solid);
      line(p.stop, css("--stop"), `${who} stop`, LightweightCharts.LineStyle.Dashed);
      line(p.target, css("--target"), `${who} target`, LightweightCharts.LineStyle.Dashed);
    }
  }

  function drawTrades(trades, firstTime) {
    const step = PERIOD[state.frame];
    const marks = trades.map((t) => ({ ...t, time: Math.floor(t.time / step) * step }))
      .filter((t) => t.time >= firstTime)
      .map((t) => t.kind === "open"
        ? { time: t.time, position: t.side === "long" ? "belowBar" : "aboveBar", shape: t.side === "long" ? "arrowUp" : "arrowDown",
            color: t.side === "long" ? css("--up") : css("--down"), text: `${t.account.split(" ").pop()} ${t.side === "long" ? "BUY" : "SELL"}` }
        : { time: t.time, position: "inBar", shape: "circle", color: t.pnl >= 0 ? css("--up") : css("--down"),
            text: `close ${money(t.pnl)}` });
    series.setMarkers(marks.sort((a, b) => a.time - b.time));
  }

  function side(d) {
    const cards = $("positions");
    cards.replaceChildren();
    if (!d.positions.length) cards.append(el("div", "empty", "No open trade on this instrument."));
    for (const p of d.positions) {
      const c = el("div", "card");
      const head = el("div", "head");
      head.append(el("span", null, p.account), el("span", p.side, p.side === "long" ? "LONG (buy)" : "SHORT (sell)"));
      c.append(head);
      for (const [k, v] of [["Opened at", fmt(p.entry)], ["Stop loss", fmt(p.stop)], ["Take profit", fmt(p.target)],
        ["Now", fmt(d.price)], ["Result so far", money(p.pnl)], ["Most it can lose", `$${p.risk.toFixed(2)}`]]) {
        const r = el("div", "row"); r.append(el("span", null, k), el("span", null, v)); c.append(r);
      }
      cards.append(c);
    }
    const list = $("trades");
    list.replaceChildren();
    const done = d.trades.filter((t) => t.kind === "close").reverse();
    if (!done.length) list.append(el("div", "empty", "No finished trades yet."));
    for (const t of done) {
      const r = el("div");
      r.append(el("span", t.side, `${t.account.split(" ").pop()} ${t.side}`), el("span", null, t.reason),
        el("span", t.pnl >= 0 ? "long" : "short", money(t.pnl)));
      list.append(r);
    }
  }

  function header(d) {
    $("sym").textContent = d.ticker;
    $("price").textContent = fmt(d.price);
    $("price").hidden = d.price == null;
    const chg = $("chg");
    chg.hidden = d.change == null;
    chg.textContent = d.change == null ? "" : `${d.change >= 0 ? "+" : ""}${(d.change * 100).toFixed(2)}% today`;
    chg.className = `chg ${d.change >= 0 ? "up" : "down"}`;
    const age = d.fetched_at ? Math.round((Date.now() - Date.parse(d.fetched_at)) / 1000) : null;
    $("fresh").textContent = d.cooldown
      ? `TradingView asked us to slow down: our record resumes in ${Math.ceil(d.cooldown / 60)} min`
      : age == null ? "no live price yet" : `our record: updated ${age}s ago` + (d.delay ? ` · prices ${d.delay} min delayed (TradingView free stock data)` : "");
    $("fresh").className = `fresh ${age != null && age < 90 ? "live" : ""}`;
    document.title = `${d.ticker} ${fmt(d.price)} · Live Charts`;
  }

  async function load() {
    if (!state.ticker) return;
    const key = `${state.ticker}|${state.frame}`;
    let reply;
    try {
      reply = await (await fetch(`/api/candles?ticker=${encodeURIComponent(state.ticker)}&tf=${state.frame}`)).json();
    } catch { $("fresh").textContent = "dashboard not reachable"; return; }
    if (!reply.ok || key !== `${state.ticker}|${state.frame}`) return;
    const d = reply.data;
    const note = $("note");
    note.hidden = d.bars.length > 1;
    note.textContent = d.frame === "1D"
      ? `Daily candles come from this system's own record, which starts ${d.record_starts || "today"}; one candle is added per day.`
      : d.cooldown ? `TradingView asked us to slow down, so our recording resumes in about ${Math.ceil(d.cooldown / 60)} min. TradingView's own chart (the other view) keeps moving.`
        : d.note || "Collecting candles: this system records TradingView prices from the moment it starts.";
    series.applyOptions({ priceFormat: { type: "price", precision: digits(d.price || 1), minMove: 1 / 10 ** digits(d.price || 1) } });
    if (state.key !== key) {
      series.setData(d.bars);
      chart.timeScale().scrollToRealTime();
      state.key = key;
    } else {
      for (const bar of d.bars) if (bar.time >= state.last) series.update(bar);
    }
    state.last = d.bars.length ? d.bars[d.bars.length - 1].time : 0;
    state.data = d;
    header(d);
    legend(d.bars[d.bars.length - 1]);
    drawPositions(d.positions);
    drawTrades(d.trades, d.bars.length ? d.bars[0].time : 0);
    side(d);
  }

  chart.subscribeCrosshairMove((p) => {
    const bar = p && p.time ? p.seriesData.get(series) : null;
    legend(bar || (state.data && state.data.bars[state.data.bars.length - 1]));
  });

  document.querySelectorAll("#views button").forEach((b) => { b.onclick = () => setView(b.dataset.view); });
  fetch("/api/candles").then((r) => r.json()).then((r) => {
    const symbols = r.ok ? r.data.symbols : [];
    if (!state.ticker && symbols.length) state.ticker = symbols[0].ticker;
    buttons(symbols);
    setView("tv");
    load();
    setInterval(load, POLL_MS);
  });
})();
