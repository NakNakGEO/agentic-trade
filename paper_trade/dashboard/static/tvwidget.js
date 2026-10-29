// TradingView's own live chart (their free embeddable chart) for one instrument, M1 by default.
// It loads straight from TradingView into this browser, so it moves in real time and does not use our request quota.
let symbols = null;

async function tvSymbols() {
  if (symbols) return symbols;
  let list = [];
  try { const msg = await (await fetch('/api/candles', {cache: 'no-store'})).json(); if (msg.ok) list = msg.data.symbols; } catch (e) { /* retried on the next call */ }
  if (list.length) symbols = Object.fromEntries(list.map(s => [s.ticker, s.tv]));
  return symbols || {};
}

export async function showTradingView(ticker, box, interval = '1') {
  const symbol = (await tvSymbols())[ticker];
  if (!box) return;
  if (!symbol) { box.textContent = `TradingView has no chart symbol for ${ticker}.`; return; }
  if (box.dataset.symbol === symbol) return;                 // already showing it: do not reload the chart
  box.dataset.symbol = symbol;
  const host = document.createElement('div'); host.className = 'tradingview-widget-container'; host.style.cssText = 'height:100%;width:100%';
  const chart = document.createElement('div'); chart.className = 'tradingview-widget-container__widget'; chart.style.cssText = 'height:calc(100% - 22px);width:100%';
  const credit = document.createElement('div'); credit.className = 'tradingview-widget-copyright'; credit.style.cssText = 'font-size:11px;height:22px';
  const link = document.createElement('a'); link.href = `https://www.tradingview.com/symbols/${symbol.replace(':', '-')}/`; link.target = '_blank'; link.rel = 'noopener nofollow';
  link.textContent = `${ticker} chart by TradingView`; credit.append(link);
  const script = document.createElement('script');
  script.src = 'https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js'; script.async = true;
  script.text = JSON.stringify({autosize: true, symbol, interval, timezone: 'Etc/UTC', style: '1', locale: 'en',
    theme: matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light', allow_symbol_change: false,
    hide_side_toolbar: false, withdateranges: true, calendar: false, support_host: 'https://www.tradingview.com'});
  host.append(chart, credit, script);
  box.replaceChildren(host);
}
