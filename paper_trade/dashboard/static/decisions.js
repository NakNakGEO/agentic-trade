// Grid of the rating each asset got on each date, coloured by rating.
import {$, el, RATING, changed, plainCall} from './util.js';

const ORDER = ['stock', 'crypto', 'forex', 'gold', 'futures'];

const tickersHeld = d => ((d.portfolio && d.portfolio.tickers) || []).map(r => Math.abs(r.exposure) >= 0.005);

export function renderDecisions(d) {
  const held = t => ((d.portfolio && d.portfolio.tickers) || []).some(r => r.ticker === t && Math.abs(r.exposure) >= 0.005);   // a trade is open now
  if (!changed('decisions', [d.decisions, d.meta.dates, d.meta.tickers, d.classes, tickersHeld(d), d.skipped])) return;
  const dates = (d.meta.dates && d.meta.dates.length ? d.meta.dates : [...new Set(d.decisions.map(x => x.date))]).slice().sort();
  const byKey = {}; d.decisions.forEach(x => byKey[x.ticker + '|' + x.date] = x);
  const tickers = [...new Set([...(d.meta.tickers || []), ...d.decisions.map(x => x.ticker)])];
  const klass = t => d.classes[t] || '';
  const rank = t => { const i = ORDER.indexOf(klass(t)); return i < 0 ? ORDER.length : i; };
  tickers.sort((a, b) => rank(a) - rank(b));
  if (!tickers.length) { $('decisions').replaceChildren(el('div', {class: 'empty'}, 'No decisions yet.')); return; }

  const table = el('table', {}), head = el('tr', {}, el('th', {}, 'Asset'));
  dates.forEach(x => head.append(el('th', {}, x.slice(5))));
  table.append(head);
  tickers.forEach(t => {
    const tr = el('tr', {}, el('td', {}, el('b', {}, t), ' ', el('span', {class: 'empty'}, klass(t))));
    dates.forEach(x => {
      const row = byKey[t + '|' + x];
      const [word, what] = row ? plainCall(row.rating, x === dates[dates.length - 1] && held(t)) : ['', ''];
      const skip = row && (d.skipped || {})[t], notOpened = !!skip && skip.date === x;     // a Buy or Sell the account could not open
      const rated = `${what}\nThe model's rating was: ${row ? row.rating : ''}. ` + (row && row.raw ? `5-day return ${row.raw}, alpha ${row.alpha}` : '5-day result not settled yet');
      tr.append(el('td', {}, row
        ? el('span', {class: 'cellr', style: `background:${RATING[row.rating] || 'var(--mute)'}` + (notOpened ? ';opacity:.6' : ''),
            title: (notOpened ? skip.why + '\n\n' : '') + rated},
          word, notOpened ? el('small', {}, 'not opened') : row.raw ? el('small', {}, row.raw) : '')
        : el('span', {class: 'empty'}, '-')));
    });
    table.append(tr);
  });
  $('decisions').replaceChildren(table);
}
