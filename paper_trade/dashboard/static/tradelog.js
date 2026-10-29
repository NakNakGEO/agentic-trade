// Trade record for one asset: how many trades won and lost, and every fill with its result.
import {$, el, money, cls, price, utc} from './util.js';

const chip = (value, label, kind) => el('div', {class: 'chip ' + (kind || '')}, el('b', {class: kind === 'win' ? 'good' : kind === 'loss' ? 'bad' : ''}, value), label);

function summary(r, open) {
  const rate = r.win_rate == null ? '-' : Math.round(r.win_rate * 100) + '%';
  return el('div', {class: 'chips'},
    chip(String(r.wins), 'won', 'win'), chip(String(r.losses), 'lost', 'loss'), chip(rate, `win rate (${r.closed} closed)`),
    chip(r.closed ? money(r.realized, true) : '-', 'made on closed trades'),
    chip(open ? money(open.pnl, true) : '-', open ? `floating on the open ${open.side}` : 'floating on the open position'),
    chip(String(r.fills), 'fills in total'));
}

const verb = side => side === 'short' ? 'shorted' : 'bought';
const actionOf = t => t.opens === 'short' ? 'SHORT' : t.closes === 'short' ? 'COVER' : t.side === 'buy' ? 'BUY' : 'SELL';

function resultCell(t) {
  if (t.pnl == null) return el('span', {class: 'badge buy'}, t.opens === 'short' ? 'entry (short)' : 'entry (long)');
  const won = t.pnl > 0, cost = t.entry_price * (t.value / t.price), pct = cost ? t.pnl / cost * 100 : 0;
  return el('span', {}, el('span', {class: 'badge ' + (won ? 'win' : 'loss')}, won ? 'WIN' : 'LOSS'), ' ',
    el('b', {class: cls(t.pnl)}, `${money(t.pnl, true)} (${pct > 0 ? '+' : ''}${pct.toFixed(1)}%)`),
    el('span', {class: 'empty'}, `  closed a ${t.closes}, ${verb(t.closes)} at avg ${price(t.entry_price)}${t.entry_date ? ' on ' + t.entry_date : ''}`));
}

export function renderTradeLog(c) {
  const box = $('tradeLog'); box.replaceChildren();
  if (!c.record) { box.append(el('div', {class: 'empty'}, 'No trades for this asset yet. Hold, or the decisions have not reached a next close.')); return; }
  box.append(summary(c.record, c.open));
  const table = el('table', {});
  table.append(el('tr', {}, ...['Filled', 'Action', 'Rating', 'Price', 'Amount', 'Result'].map((h, i) => el('th', {class: i === 3 || i === 4 ? 'n' : ''}, h))));
  c.trades.forEach(t => table.append(el('tr', {}, el('td', {}, utc(t.fill_date)),
    el('td', {}, el('b', {class: t.pnl == null ? '' : cls(t.pnl)}, actionOf(t))), el('td', {}, t.rating),
    el('td', {class: 'n'}, price(t.price)), el('td', {class: 'n'}, '$' + t.value.toFixed(2)), el('td', {}, resultCell(t)))));
  if (c.open) table.append(el('tr', {}, el('td', {}, 'now'), el('td', {}, el('span', {class: 'badge open'}, 'OPEN ' + c.open.side.toUpperCase())), el('td', {}, ''),
    el('td', {class: 'n'}, price(c.open.last_price)), el('td', {class: 'n'}, '$' + Math.abs(c.open.shares * c.open.last_price).toFixed(2)),
    el('td', {}, el('b', {class: cls(c.open.pnl)}, money(c.open.pnl, true)), el('span', {class: 'empty'}, `  floating, ${verb(c.open.side)} at avg ${price(c.open.entry_price)} since ${utc(c.open.entry_date)}`))));
  c.pending.forEach(p => table.append(el('tr', {}, el('td', {}, p.date), el('td', {}, 'waiting'), el('td', {}, p.rating), el('td', {}, ''), el('td', {}, ''),
    el('td', {class: 'empty'}, 'fills at the next close'))));
  if (c.trades.length || c.open || c.pending.length) box.append(el('div', {class: 'scroll'}, table));
  else box.append(el('div', {class: 'empty'}, 'No fills yet: every decision so far kept this asset out of the market.'));
}
