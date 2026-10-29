// "Market now": near-live prices, updated in place every few seconds and flashing when they move.
import {$, el, cls, price, flash} from './util.js';

const REFRESH_MS = 8000;
const SVGNS = 'http://www.w3.org/2000/svg';
const tiles = new Map();              // ticker -> its tile's elements
let quotes = new Map();               // symbol -> latest good quote
const listeners = [];

export const getQuotes = () => quotes;
export const onQuotes = fn => listeners.push(fn);

function spark(values, up) {
  const svg = document.createElementNS(SVGNS, 'svg');
  svg.setAttribute('viewBox', '0 0 120 34'); svg.setAttribute('preserveAspectRatio', 'none');
  const lo = Math.min(...values), hi = Math.max(...values), span = (hi - lo) || 1;
  const line = document.createElementNS(SVGNS, 'polyline');
  line.setAttribute('fill', 'none'); line.setAttribute('stroke', up ? 'var(--good)' : 'var(--bad)'); line.setAttribute('stroke-width', '1.6');
  line.setAttribute('points', values.map((v, i) => `${(i / (values.length - 1 || 1) * 118 + 1).toFixed(1)},${(31 - (v - lo) / span * 28).toFixed(1)}`).join(' '));
  svg.append(line);
  return svg;
}

function build(r) {
  const px = el('div', {class: 'px'}), chg = el('div', {class: 'chg'}), lag = el('div', {class: 'lag'}), chart = el('div');
  const root = el('div', {class: 'card mk'}, el('div', {class: 'sym'}, el('span', {}, r.ticker), el('small', {}, r.class)), px, chg, chart, lag);
  return {root, px, chg, lag, chart, last: null};
}

function update(t, r) {
  if (r.error) { t.px.textContent = ''; t.chg.textContent = ''; t.chart.replaceChildren(); t.lag.className = 'lag warn'; t.lag.textContent = r.error; return; }
  t.px.textContent = price(r.price);
  if (t.last !== null && r.price !== t.last) flash(t.px, r.price > t.last ? 1 : -1);      // it ticked: show which way
  t.last = r.price;
  t.chg.className = 'chg ' + cls(r.change);
  t.chg.textContent = (r.change > 0 ? '+' : '') + (r.change * 100).toFixed(2) + '% today';
  t.chart.replaceChildren(spark(r.spark, r.change >= 0));
  const late = r.lag_minutes > 5;
  t.lag.className = 'lag' + (late ? ' warn' : '');
  t.lag.textContent = `last bar ${r.lag_minutes} min ago` + (late ? ' (delayed feed)' : '');
}

async function refresh() {
  try {
    const msg = await (await fetch('/api/market' + location.search, {cache: 'no-store'})).json();
    if (!msg.ok) return;
    msg.data.forEach(r => {
      let t = tiles.get(r.ticker);
      if (!t) { t = build(r); tiles.set(r.ticker, t); $('market').append(t.root); }
      update(t, r);
    });
    quotes = new Map(msg.data.filter(r => !r.error).map(r => [r.symbol, r]));
    $('marketClock').textContent = '· checked ' + new Date().toLocaleTimeString([], {hour12: false});
    listeners.forEach(fn => fn(quotes));
  } catch (e) { /* keep the last prices on screen */ }
}

export function startMarket() {
  refresh();
  setInterval(refresh, REFRESH_MS);
}
