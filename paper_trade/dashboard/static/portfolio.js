// The paper portfolio: profit tiles, a live-valued tile, the comparison chart, and per-asset win/loss rows.
import {$, el, money, cls, flash, changed, level} from './util.js';
import {getQuotes} from './market.js';

const SVGNS = 'http://www.w3.org/2000/svg';
let current = null;                   // latest portfolio payload, kept so live prices can re-value it
let lastLive = null;

const tile = (value, label, c, id) => el('div', {class: 'card tile'}, el('b', {class: c || '', id: id || ''}, value), el('span', {}, label));
const MODE_TEXT = {long_short: '· long and short: a Sell or Underweight opens a short trade that profits when the price falls',
  full_size: '· long and short, full size: every Overweight or Underweight call also commits 100% of the money',
  fixed_lot: '· fixed lot like the MT5 demo: every directional call trades the same small lot with a stop and a take-profit, so the money is leveraged and the benchmarks below are not',
  long_only: '· long only: it can only buy, then sell what it holds, so bearish calls from flat do nothing'};
// Net position as a share of the money: negative means short.
const net = x => Math.abs(x) < 0.005 ? '0%' : x < 0 ? Math.round(-x * 100) + '% short' : Math.round(x * 100) + '% long';
// In the fixed-lot account every trade is one small lot, so a share of the money means nothing: say long or short and the lot.
const side = (x, d, t, lot) => d.mode !== 'fixed_lot' ? net(x) : Math.abs(x) < 0.005 ? ((d.skipped || {})[t] ? 'not opened' : 'no trade') : (x < 0 ? 'SHORT' : 'LONG') + (lot || d.lot ? ` · ${lot || d.lot} lot` : '');

// What the paper positions are worth at live prices; assets with no live quote keep their last close.
function liveTotal(p) {
  const quotes = getQuotes();
  let total = 0, covered = 0;
  for (const r of p.tickers) {
    const quote = quotes.get(r.symbol);
    if (quote) covered += 1;
    total += r.cash + r.shares * (quote ? quote.price : r.last_price);
  }
  return {total, covered, of: p.tickers.length};
}

export function updateLive() {
  const value = $('liveValue');
  if (!current || !value) return;
  const {total, covered, of} = liveTotal(current), gain = total - current.cash;
  value.textContent = '$' + total.toFixed(2);
  value.className = cls(gain);
  $('liveNote').textContent = `${money(gain, true)} vs the $${current.cash.toFixed(0)} start, at live prices (${covered} of ${of} assets live)`;
  if (lastLive !== null && Math.abs(total - lastLive) > 1e-9) flash(value.parentElement, total > lastLive ? 1 : -1);
  lastLive = total;
  const quotes = getQuotes();                                     // the "Price now" column follows the live quotes too
  document.querySelectorAll('#tickers [data-price]').forEach(cell => {
    const quote = quotes.get(cell.dataset.price);
    if (quote) cell.textContent = level(quote.price);
  });
}

function lineChart(series, cash) {
  const lines = [[series.strategy, 'var(--accent)', 2.4], [series.spy, 'var(--mute)', 1.5], [series.hold, 'var(--under)', 1.5]];
  const all = lines.flatMap(l => l[0]);
  if (all.length < 2) return el('div', {class: 'empty'}, 'Not enough days yet.');
  const t = s => Date.parse(s), xs = all.map(p => t(p[0])), ys = all.map(p => p[1]).concat([cash]);
  const x0 = Math.min(...xs), x1 = Math.max(...xs), lo = Math.min(...ys), hi = Math.max(...ys), pad = (hi - lo) * .12 || 1;
  const W = 760, H = 240, L = 46, R = 10, T = 10, B = 24;
  const X = v => L + (t(v) - x0) / ((x1 - x0) || 1) * (W - L - R), Y = v => T + (1 - (v - (lo - pad)) / (hi - lo + 2 * pad)) * (H - T - B);
  const svg = document.createElementNS(SVGNS, 'svg');
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  const add = (tag, attrs, text) => { const n = document.createElementNS(SVGNS, tag); for (const k in attrs) n.setAttribute(k, attrs[k]); if (text) n.textContent = text; svg.append(n); };
  for (let i = 0; i <= 4; i++) {
    const v = lo - pad + (hi - lo + 2 * pad) * i / 4;
    add('line', {x1: L, x2: W - R, y1: Y(v), y2: Y(v), stroke: 'var(--line)'});
    add('text', {x: L - 6, y: Y(v) + 4, 'text-anchor': 'end', 'font-size': 11, fill: 'var(--mute)'}, '$' + v.toFixed(2));
  }
  add('line', {x1: L, x2: W - R, y1: Y(cash), y2: Y(cash), stroke: 'var(--mute)', 'stroke-dasharray': '4 4'});
  add('text', {x: L, y: H - 6, 'font-size': 11, fill: 'var(--mute)'}, series.strategy[0][0]);
  add('text', {x: W - R, y: H - 6, 'text-anchor': 'end', 'font-size': 11, fill: 'var(--mute)'}, series.strategy[series.strategy.length - 1][0]);
  lines.forEach(([pts, color, w]) => add('polyline', {fill: 'none', stroke: color, 'stroke-width': w, 'stroke-linejoin': 'round', points: pts.map(p => X(p[0]) + ',' + Y(p[1])).join(' ')}));
  return svg;
}

function assetTable(p, d) {
  const t = $('tickers'); t.replaceChildren();
  const share = p.cash / p.tickers.length;
  const levels = d.mode === 'fixed_lot';          // only the fixed-lot account trades with a stop and a take-profit
  const timed = levels && p.tickers.some(r => r.deadline);      // some trade has a time limit
  const heads = [['Asset'], ['Class'], ['Strategy profit', 'What the trades on this asset made or lost so far, after fees.'],
    ['If just bought and held', `A comparison only, not a trade. What this asset's share of the money ($${share.toFixed(2)}, which is $${p.cash.toFixed(0)} split equally) would have made if it had been bought at the start and simply held: no stop, no target, no leverage. It can move even when the model made no trade.`],
    ['Position now', 'The trade open right now on this asset, or no trade.'],
    ...(levels ? [['Entry', 'The price the open trade was opened at.'],
      ['Price now', 'The live price of this asset right now.'],
      ['Stop loss', 'The trade closes at a loss if the price reaches this level.'],
      ['Take profit', 'The trade closes at a profit if the price reaches this level (twice as far from the entry as the stop).'],
      ['Win at target', 'What the trade makes if it ends at the take profit, after the fees on both sides.'],
      ['Lose at stop', 'What the trade loses if it ends at the stop loss, after the fees on both sides.'],
      ...(timed ? [['Closes by (UTC)', 'A trade with a time limit is closed at the market by this time if neither the stop nor the take profit came first.']] : [])] : []),
    ['Wins'], ['Losses'], ['Win rate'], ['Realized'], ['Open P&L']];
  t.append(el('tr', {}, ...heads.map(([h, tip], i) => el('th', {class: i > 1 ? 'n' : '', title: tip || ''}, h))));
  p.tickers.forEach(r => t.append(el('tr', {}, el('td', {}, r.ticker), el('td', {class: 'empty'}, r.class),
    el('td', {class: 'n ' + cls(r.strategy)}, money(r.strategy, true)), el('td', {class: 'n ' + cls(r.hold)}, money(r.hold, true)),
    el('td', {class: 'n', title: ((d.skipped || {})[r.ticker] || {}).why || ''}, side(r.exposure, d, r.ticker, r.lot)),
    ...(levels ? [el('td', {class: 'n'}, r.open ? level(r.open_entry_price) : '-'),
      el('td', {class: 'n', 'data-price': r.symbol}, level(r.last_price)),
      el('td', {class: 'n bad'}, r.open ? level(r.stop) : '-'), el('td', {class: 'n good'}, r.open ? level(r.target) : '-'),
      el('td', {class: 'n good'}, r.open && r.win != null ? money(r.win, true) : '-'),
      el('td', {class: 'n bad'}, r.open && r.lose != null ? money(r.lose, true) : '-'),
      ...(timed ? [el('td', {class: 'n'}, r.open && r.deadline ? r.deadline.slice(5, 16).replace('T', ' ') : '-')] : [])] : []),
    el('td', {class: 'n good'}, String(r.wins)), el('td', {class: 'n bad'}, String(r.losses)),
    el('td', {class: 'n'}, r.win_rate == null ? '-' : Math.round(r.win_rate * 100) + '%'),
    el('td', {class: 'n ' + cls(r.realized)}, r.closed ? money(r.realized, true) : '-'),
    el('td', {class: 'n ' + cls(r.open_pnl)}, r.open ? money(r.open_pnl, true) : '-'))));
}

export function renderPortfolio(d) {
  $('modeNote').textContent = d.style_note ? '· ' + d.style_note : MODE_TEXT[d.mode] || '';
  if (!changed('portfolio', [d.portfolio, d.mode, d.lot, d.skipped])) { updateLive(); return; }          // same numbers as before: leave the screen alone
  const p = d.portfolio, tiles = $('tiles'); tiles.replaceChildren();
  current = p && !p.error ? p : null;
  if (!current) {
    tiles.append(el('div', {class: 'empty'}, p ? 'Waiting for a tradeable decision: ' + p.error : 'No decisions yet, so the paper portfolio is still at its starting cash.'));
    $('chart').replaceChildren(); $('tickers').replaceChildren(); return;
  }
  const profit = p.end.strategy - p.cash, r = p.record;
  tiles.append(
    tile('', 'live value now', '', 'liveValue'),
    tile('$' + p.end.strategy.toFixed(2), `value at the last completed close (started with $${p.cash.toFixed(0)})`),
    tile(money(profit, true), 'profit or loss at that close', cls(profit)),
    tile(money(p.per_day, true) + '/day', `average over ${p.days} days`, cls(p.per_day)),
    tile(`${r.wins} won · ${r.losses} lost`, `closed trades${r.closed ? ` · ${Math.round(r.wins / r.closed * 100)}% win rate` : ' (none closed yet)'}`),
    tile(money(r.realized, true), 'made on closed trades', cls(r.realized)),
    tile(money(r.open_pnl, true), 'floating on open positions', cls(r.open_pnl)),
    tile(money(p.best_day, true), 'best single day', 'good'), tile(money(p.worst_day, true), 'worst single day', 'bad'),
    tile(money(p.end.strategy - p.end.spy, true), p.live ? 'versus holding the same pairs' : 'versus SPY buy and hold', cls(p.end.strategy - p.end.spy)),
    tile(money(p.end.strategy - p.end.hold, true), 'versus holding the same assets', cls(p.end.strategy - p.end.hold)),
    d.mode === 'fixed_lot' ? tile(String(p.tickers.filter(r => Math.abs(r.exposure) >= 0.005).length), `trades open now · ${p.trades} fills`) : tile(net(p.exposure), `net position now · ${p.trades} fills`));
  // The live tile carries a note line of its own, updated whenever a new price arrives.
  const holder = $('liveValue').parentElement; holder.querySelector('span').id = 'liveNote';
  lastLive = null; updateLive();
  $('chart').replaceChildren(lineChart(p.series, p.cash));
  assetTable(p, d);
  updateLive();                                                   // the new table's price cells start from the live quotes
}
