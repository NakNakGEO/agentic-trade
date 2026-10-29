// The scorecard: is the model's call right? Each row grades the calls a set time after they landed, next to three simple guesses.
import {$, el, changed} from './util.js';

const pct = row => row.right_pct == null ? '-' : row.right_pct.toFixed(1) + '%';
const bps = v => v == null ? '-' : (v > 0 ? '+' : '') + v.toFixed(1);

export function renderScorecard(d) {
  const card = $('scorecard');
  const s = d.scorecard;
  card.style.display = s ? '' : 'none';
  if (!s || !changed('scorecard', s)) return;
  $('scoreNote').textContent = `· ${s.model}: ${s.calls} calls (${s.holds} Hold)`;
  const table = $('scoreTable'); table.replaceChildren();
  table.append(el('tr', {}, ...['After the call', 'Calls graded', 'Right', 'Average move in its favour', 'Always sell', 'Always buy', "TradingView's rating", ''].map((h, i) =>
    el('th', {class: i > 0 && i < 7 ? 'n' : '', title: i === 3 ? 'In basis points: 1 is 0.01%. Positive means the price moved the way the call said.' : ''}, h))));
  Object.entries(s.horizons).forEach(([name, row]) => {
    const b = row.baselines;
    table.append(el('tr', {class: row.enough ? '' : 'empty'}, el('td', {}, el('b', {}, name)), el('td', {class: 'n'}, String(row.n)),
      el('td', {class: 'n'}, el('b', {}, pct(row))), el('td', {class: 'n'}, bps(row.avg_bps)),
      el('td', {class: 'n'}, pct(b.sell)), el('td', {class: 'n'}, pct(b.buy)), el('td', {class: 'n'}, pct(b.tv)),
      el('td', {}, row.enough ? '' : el('span', {class: 'badge buy'}, 'too few to judge'))));
  });
}
