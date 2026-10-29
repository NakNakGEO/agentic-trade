// The account's trades laid out like TradingView's trading panel: Positions, Orders and Trade history.
// One row per trade (Positions, Trade history) or per order (Orders), so two trades on one pair show as two rows.
import {$, el, money, cls, changed, level} from './util.js';
import {getQuotes} from './market.js';

const TABS = [['positions', 'Positions'], ['orders', 'Orders'], ['history', 'Trade history']];
const ENDED = {'Take-profit': 'Take profit', 'Stop-loss': 'Stop loss', 'Time limit': 'Time limit', 'New call': 'New call'};
let tab = 'positions', data = null;

const head = cols => el('tr', {}, ...cols.map(([h, tip, num]) => el('th', {class: num ? 'n' : '', title: tip || ''}, h)));
const num = (text, c) => el('td', {class: 'n ' + (c || '')}, text);
const dash = v => v == null ? '-' : level(v);
const sideCell = side => el('td', {}, el('b', {style: `color:var(${/^(Buy|long)$/.test(side) ? '--accent' : '--bad'})`}, side[0].toUpperCase() + side.slice(1)));
// An amount with how far the price has to move for it, underneath.
const amount = (value, move, c) => value == null ? num('-') : el('td', {class: 'n ' + c}, money(value, true), el('div', {class: 'empty'}, move));
const badge = (pnl) => el('span', {class: 'badge ' + (pnl > 0 ? 'win' : 'loss')}, pnl > 0 ? 'WIN' : 'LOSS');
const resultCell = o => o.result === 'open'
  ? el('td', {class: 'n ' + cls(o.pnl)}, 'Open ', money(o.pnl, true), el('span', {class: 'empty'}, ' now'))
  : el('td', {class: 'n'}, badge(o.pnl), ' ', el('b', {class: cls(o.pnl)}, money(o.pnl, true)));

function positions(rows) {
  const table = el('table', {});
  table.append(head([['Trade', 'Number of the trade, in the order they were opened.'], ['Pair'], ['Side'], ['Lot', '', 1], ['Entry', '', 1], ['Price now', '', 1],
    ['Take profit', '', 1], ['Stop loss', '', 1],
    ['Win at take profit', 'What the trade makes if the price reaches the take profit, after fees, and how far the price has to move.', 1],
    ['Lose at stop loss', 'What the trade loses if the price reaches the stop loss, after fees, and how far the price has to move.', 1],
    ['Open P&L', 'Floating result before the exit fee.', 1], ['Opened (UTC)'], ['Closes by (UTC)', 'The time limit: it is closed at the market by then if neither level came first.']]));
  rows.forEach(r => table.append(el('tr', {'data-symbol': r.symbol, 'data-sign': r.sign, 'data-units': r.units, 'data-usd': r.usd_base ? 1 : 0, 'data-entry': r.entry},
    el('td', {}, '#' + r.trade), el('td', {}, r.ticker), sideCell(r.side), num(r.lot), num(level(r.entry)), el('td', {class: 'n px'}, level(r.last)),
    num(dash(r.target), 'good'), num(dash(r.stop), 'bad'), amount(r.win, r.to_target, 'good'), amount(r.lose, r.to_stop, 'bad'),
    el('td', {class: 'n pl ' + cls(r.pnl)}, money(r.pnl, true)), el('td', {}, r.opened), el('td', {}, r.expiry))));
  return rows.length ? table : el('div', {class: 'empty'}, 'No trade is open right now.');
}

function orders(rows) {
  const table = el('table', {});
  table.append(head([['Order', 'Every trade has an order that opens it and, once it is closed, an order that closes it. The number is the trade.'], ['Pair'], ['Side'], ['Lot', '', 1],
    ['Fill price', '', 1], ['Take profit', '', 1], ['Stop loss', '', 1],
    ['Win at take profit', 'What the open trade makes if the price reaches the take profit, after fees, and how far the price has to move.', 1],
    ['Lose at stop loss', 'What the open trade loses if the price reaches the stop loss, after fees, and how far the price has to move.', 1],
    ['Status'], ['Result', 'An open trade: its floating result now. A closed trade: won or lost, after fees.', 1], ['Time (UTC)']]));
  rows.forEach(o => table.append(el('tr', {},
    el('td', {}, el('b', {}, o.kind === 'open' ? 'Opens ' : 'Closes '), '#' + o.trade), el('td', {}, o.ticker), sideCell(o.side), num(o.lot), num(level(o.fill)),
    num(dash(o.tp), 'good'), num(dash(o.sl), 'bad'), amount(o.win, o.win_move, 'good'), amount(o.lose, o.lose_move, 'bad'),
    el('td', {}, el('span', {class: 'badge win'}, o.status)), resultCell(o), el('td', {}, o.time))));
  return rows.length ? table : el('div', {class: 'empty'}, 'No orders yet.');
}

function history(rows) {
  const table = el('table', {});
  table.append(head([['Trade'], ['Pair'], ['Side'], ['Lot', '', 1], ['Entry', '', 1], ['Exit', '', 1], ['Result', 'After both fees.', 1],
    ['Price move', 'How far the price moved in the trade\'s favour (negative: against it), in pips for forex and dollars of price for the rest.', 1],
    ['Ended by'], ['Opened (UTC)'], ['Closed (UTC)'], ['Held', '', 1]]));
  rows.forEach(r => table.append(el('tr', {}, el('td', {}, '#' + r.trade), el('td', {}, r.ticker), sideCell(r.side), num(r.lot), num(level(r.entry)), num(level(r.exit)),
    el('td', {class: 'n'}, badge(r.pnl), ' ', el('b', {class: cls(r.pnl)}, money(r.pnl, true))), num(r.move, r.move[0] === '-' ? 'bad' : 'good'),
    el('td', {}, ENDED[r.reason] || r.reason), el('td', {}, r.opened), el('td', {}, r.closed), num(r.minutes >= 120 ? (r.minutes / 60).toFixed(1) + ' h' : r.minutes + ' min'))));
  return rows.length ? table : el('div', {class: 'empty'}, 'No trade has finished yet.');
}

// How much money the open trades could lose if every stop were hit, and whether the account has a cap on that.
const riskLine = r => !r ? [] : [el('div', {class: 'empty', title: 'The sum of what each open trade loses if it reaches its stop loss, before fees.'},
  `Open risk: ${money(r.open)} in ${r.trades} trade${r.trades === 1 ? '' : 's'}` + (r.share != null ? ` (${(r.share * 100).toFixed(1)}% of the account)` : '') + ' · ' +
  (r.cap == null ? 'no risk cap: the account can lose everything' : `risk cap ${Math.round(r.cap * 100)}% of the account`))];

function draw() {
  if (!$('blotter')) return;
  const tabs = el('div', {class: 'tabs'}, ...TABS.map(([key, label]) => el('button', {class: 'pill' + (key === tab ? ' on' : ''), 'data-tab': key}, `${label} ${data[key].length}`)));
  const body = tab === 'positions' ? positions(data.positions) : tab === 'orders' ? orders(data.orders) : history(data.history);
  $('blotterTabs').replaceChildren(tabs); $('blotterBody').replaceChildren(...riskLine(data.risk), el('div', {class: 'scroll'}, body));
  updateBlotterLive();
}

// Every new quote re-values the open positions' price and floating result.
export function updateBlotterLive() {
  const quotes = getQuotes();
  document.querySelectorAll('#blotterBody tr[data-symbol]').forEach(row => {
    const quote = quotes.get(row.dataset.symbol);
    if (!quote) return;
    const p = quote.price, d = row.dataset, pnl = d.sign * d.units * (d.usd === '1' ? 1 / p : 1) * (p - d.entry);
    row.querySelector('.px').textContent = level(p);
    const cell = row.querySelector('.pl'); cell.textContent = money(pnl, true); cell.className = 'n pl ' + cls(pnl);
  });
}

export function renderBlotter(d) {
  const card = $('blotter'); if (!card) return;
  card.style.display = d.blotter ? '' : 'none';                      // only the live accounts have orders
  if (!d.blotter) return;
  data = d.blotter;
  if (changed('blotter', [data, tab])) draw(); else updateBlotterLive();
}

document.addEventListener('click', e => {
  const button = e.target.closest('#blotter button');
  if (button && data && button.dataset.tab) { tab = button.dataset.tab; draw(); }
});
