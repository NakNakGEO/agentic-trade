// Daily candles for one asset with the paper trades drawn on them: fills, and each trade's line coloured win or loss.
import {$, el, price, money, utc} from './util.js';
import {renderTradeLog} from './tradelog.js';

const SVGNS = 'http://www.w3.org/2000/svg';
let chosen = null, loadedAt = -1, announced = null;

// Tell the rest of the page (the TradingView chart) which instrument is picked.
const announce = () => { if (chosen !== announced) { announced = chosen; window.dispatchEvent(new CustomEvent('instrument', {detail: chosen})); } };

export function renderPicker(d) {
  const names = [...new Set([...(d.meta.tickers || []), ...d.decisions.map(x => x.ticker)])];
  if (!names.length) return;
  if (!chosen || !names.includes(chosen)) { chosen = (d.decisions[0] || {}).ticker || names[0]; loadedAt = -1; }
  announce();
  const key = names.join(',') + '|' + chosen, box = $('picker');
  if (box.dataset.key !== key) {                      // rebuild only on change, or clicks land on a removed button
    box.dataset.key = key; box.replaceChildren();
    names.forEach(n => {
      const b = el('button', {class: n === chosen ? 'on' : ''}, n);
      b.onclick = () => { chosen = n; loadedAt = -1; renderPicker(d); reload(); announce(); };
      box.append(b);
    });
  }
  if (loadedAt !== d.cells_done) { loadedAt = d.cells_done; reload(); }          // redraw when a new decision lands
}

export async function reload() {
  if (!chosen) return;
  const q = new URLSearchParams(location.search); q.set('ticker', chosen);
  try {
    const msg = await (await fetch('/api/chart?' + q, {cache: 'no-store'})).json();
    if (!msg.ok) throw new Error(msg.error);
    draw(msg.data);
  } catch (e) { $('tradeChart').replaceChildren(el('div', {class: 'empty'}, 'Chart unavailable: ' + String(e.message || e).slice(0, 120))); }
}

function draw(c) {
  const box = $('tradeChart'), sum = $('chartSummary');
  if (c.error || !c.bars.length) { box.replaceChildren(el('div', {class: 'empty'}, c.error || 'No price history.')); sum.textContent = ''; $('tradeLog').replaceChildren(); return; }
  const r = c.record, count = f => c.trades.filter(f).length;
  const kinds = [['buy', count(t => t.opens === 'long')], ['sell', count(t => t.closes === 'long')],
    ['short', count(t => t.opens === 'short')], ['cover', count(t => t.closes === 'short')]].filter(([, k]) => k);
  sum.textContent = `${c.ticker}: ${c.decisions.length} decision${c.decisions.length === 1 ? '' : 's'}`
    + (kinds.length ? ', ' + kinds.map(([name, k]) => `${k} ${name}${k === 1 ? '' : 's'}`).join(', ') : ', no trades')
    + (r && r.closed ? ` · ${r.wins} won, ${r.losses} lost` : '') + (c.pending.length ? `, ${c.pending.length} waiting for the next close` : '')
    + (!c.decisions.length ? ' (no decisions for this asset yet, price only)' : '');

  const W = 920, T = 14, HP = 300, GAP = 12, HE = 54, B = 26, L = 62, R = 12, H = T + HP + GAP + HE + B;
  const svg = document.createElementNS(SVGNS, 'svg'); svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  const add = (tag, attrs, text, title) => {
    const n = document.createElementNS(SVGNS, tag); for (const k in attrs) n.setAttribute(k, attrs[k]);
    if (text) n.textContent = text;
    if (title) { const t = document.createElementNS(SVGNS, 'title'); t.textContent = title; n.append(t); }
    svg.append(n); return n;
  };
  const n = c.bars.length, bw = (W - L - R) / n, X = i => L + (i + .5) * bw, idx = {};
  c.bars.forEach((b, i) => idx[b[0]] = i);
  const at = date => { let k = -1; c.bars.forEach((b, i) => { if (b[0] <= date) k = i; }); return k; };   // last bar on or before a date
  let lo = Math.min(...c.bars.map(b => b[3])), hi = Math.max(...c.bars.map(b => b[2]));
  const pad = (hi - lo) * .06 || 1; lo -= pad; hi += pad;
  const Y = v => T + (1 - (v - lo) / (hi - lo)) * HP;

  for (let g = 0; g <= 5; g++) {
    const v = lo + (hi - lo) * g / 5;
    add('line', {x1: L, x2: W - R, y1: Y(v), y2: Y(v), stroke: 'var(--line)'});
    add('text', {x: L - 6, y: Y(v) + 4, 'text-anchor': 'end', 'font-size': 11, fill: 'var(--mute)'}, price(v));
  }
  c.bars.forEach(([d, o, h, l, cl], i) => {
    const color = cl >= o ? 'var(--good)' : 'var(--bad)', x = X(i), w = Math.max(2, bw * .62);
    add('line', {x1: x, x2: x, y1: Y(h), y2: Y(l), stroke: color, 'stroke-width': 1.2});
    add('rect', {x: x - w / 2, y: Y(Math.max(o, cl)), width: w, height: Math.max(1.2, Math.abs(Y(o) - Y(cl))), fill: color}, '',
      `${d}  open ${price(o)}  high ${price(h)}  low ${price(l)}  close ${price(cl)}`);
  });
  const step = Math.ceil(n / 8);
  c.bars.forEach((b, i) => { if (i % step === 0) add('text', {x: X(i), y: H - 8, 'text-anchor': 'middle', 'font-size': 11, fill: 'var(--mute)'}, b[0].slice(5)); });

  c.decisions.forEach(dc => {
    const i = at(dc.date); if (i < 0) return;
    add('circle', {cx: X(i), cy: Y(c.bars[i][4]), r: 5.5, fill: 'none', stroke: 'var(--mute)', 'stroke-width': 2}, '', `Decision on ${dc.date}: ${dc.rating}. The paper order fills at the next close.`);
  });

  // Each closed trade (a long sold, or a short bought back): a line from its average entry to where it closed,
  // green if it won, red if it lost. A short that wins slopes down.
  const verb = side => side === 'short' ? 'shorted' : 'bought';
  c.trades.filter(t => t.pnl != null && t.entry_date in idx && t.fill_date in idx).forEach(t => {
    const won = t.pnl > 0, color = won ? 'var(--good)' : 'var(--bad)', x0 = X(idx[t.entry_date]), x1 = X(idx[t.fill_date]);
    add('line', {x1: x0, y1: Y(t.entry_price), x2: x1, y2: Y(t.price), stroke: color, 'stroke-width': 2.4, 'stroke-dasharray': '6 4'}, '',
      `${won ? 'WIN' : 'LOSS'} ${money(t.pnl, true)} on a ${t.closes}: ${verb(t.closes)} at avg ${price(t.entry_price)} on ${t.entry_date}, closed at ${price(t.price)} on ${t.fill_date}`);
    add('circle', {cx: x0, cy: Y(t.entry_price), r: 4, fill: color});
  });
  if (c.open && c.open.entry_date in idx) {                       // the position still held: floating result so far
    const o = c.open, color = o.pnl >= 0 ? 'var(--good)' : 'var(--bad)', last = n - 1;
    add('line', {x1: X(idx[o.entry_date]), y1: Y(o.entry_price), x2: X(last), y2: Y(o.last_price), stroke: color, 'stroke-width': 2.4, 'stroke-dasharray': '2 4'}, '',
      `OPEN ${o.side}, floating ${money(o.pnl, true)}: ${verb(o.side)} at avg ${price(o.entry_price)} on ${o.entry_date}`);
    add('circle', {cx: X(idx[o.entry_date]), cy: Y(o.entry_price), r: 4, fill: color});
    add('text', {x: X(last) - 6, y: Y(o.last_price) - 10, 'text-anchor': 'end', 'font-size': 11.5, 'font-weight': 700, fill: color,
      stroke: 'var(--card)', 'stroke-width': 4, 'stroke-linejoin': 'round', 'paint-order': 'stroke'}, `OPEN ${o.side.toUpperCase()} ${money(o.pnl, true)}`);
  }

  // Fill markers. A fill that is a buy points up (below the candle), a sell points down (above it).
  // Closing a trade takes the colour of its result; opening a long is blue and opening a short is orange.
  // A long-to-short flip is two fills on one day, so later fills on the same candle are stacked outward.
  const stacked = {};
  c.trades.forEach(t => {
    const i = idx[t.fill_date]; if (i === undefined) return;
    const up = t.side === 'buy', x = X(i), closing = t.pnl != null, slot = stacked[i] = (stacked[i] ?? -1) + 1;
    const color = closing ? (t.pnl > 0 ? 'var(--good)' : 'var(--bad)') : t.opens === 'short' ? 'var(--under)' : 'var(--accent)';
    const y = (up ? Y(c.bars[i][3]) + 16 : Y(c.bars[i][2]) - 16) + (up ? 1 : -1) * slot * 34, d = up ? 9 : -9;
    const action = t.opens === 'short' ? 'SHORT' : t.closes === 'short' ? 'COVER' : up ? 'BUY' : 'SELL';
    add('polygon', {points: `${x},${y - d} ${x - 8},${y + d} ${x + 8},${y + d}`, fill: color}, '',
      `${action} ${t.rating}\nfilled ${utc(t.fill_date)} at ${price(t.price)}\nvalue $${t.value.toFixed(2)}`
      + (closing ? `\n${t.pnl > 0 ? 'WIN' : 'LOSS'} ${money(t.pnl, true)} (closed a ${t.closes})` : '') + `\ndecision made ${t.decision_date}`);
    const label = closing ? `${t.pnl > 0 ? 'WIN' : 'LOSS'} ${money(t.pnl, true)}` : `${action} ${t.rating}`;
    add('text', {x, y: up ? y + 24 : y - 14, 'text-anchor': 'middle', 'font-size': 11.5, 'font-weight': 700, fill: color,
      stroke: 'var(--card)', 'stroke-width': 4, 'stroke-linejoin': 'round', 'paint-order': 'stroke'}, label);
  });

  const ey = T + HP + GAP;
  add('text', {x: L - 6, y: ey + 10, 'text-anchor': 'end', 'font-size': 10, fill: 'var(--mute)'}, '100%');
  add('text', {x: L - 6, y: ey + HE, 'text-anchor': 'end', 'font-size': 10, fill: 'var(--mute)'}, '0%');
  add('line', {x1: L, x2: W - R, y1: ey + HE, y2: ey + HE, stroke: 'var(--line)'});
  c.exposure.forEach(([d, v]) => {                                // blue while long, orange while short
    const i = idx[d]; if (i === undefined || v === 0) return;
    const size = Math.min(1, Math.abs(v));
    add('rect', {x: X(i) - bw * .45, y: ey + HE * (1 - size), width: Math.max(1.5, bw * .9), height: HE * size,
      fill: v > 0 ? 'var(--accent)' : 'var(--under)', opacity: .65}, '',
      `${d}: ${(Math.abs(v) * 100).toFixed(0)}% of this asset's slice, ${v > 0 ? 'long' : 'short'}`);
  });
  box.replaceChildren(svg);
  renderTradeLog(c);
}
