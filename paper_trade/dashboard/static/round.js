// Today's round of calls, pair by pair: which of the 11 agents have finished, which one is working now, and the call when it lands.
import {$, el, plainCall, mins, changed} from './util.js';

const STATUS = {done: ['Done', 'win'], working: ['Working', 'open'], paused: ['No activity', 'loss'], waiting: ['Waiting', 'buy']};
const time = s => s < 90 ? s + ' s' : mins(s);
const tokens = n => n >= 1e6 ? (n / 1e6).toFixed(2) + 'M' : n >= 1000 ? Math.round(n / 1000) + 'k' : String(n);

function heading(r) {
  const parts = [`${r.day}`, `started ${r.started} UTC`, `${r.done} of ${r.total} pairs done`];
  if (r.done === r.total) parts.push(`finished in ${time(r.elapsed)}`);
  else parts.push(`${time(r.elapsed)} so far`, r.left ? `about ${time(r.left)} left (rough)` : 'time left: not enough finished pairs to guess yet');
  return '· ' + parts.join(' · ');
}

// How the call schedule is keeping up: the interval, how long a round really takes, and slots skipped because the model was still working.
function paceText(p) {
  if (!p) return '';
  let text = ` Calls are made every ${p.every} minutes` + (p.typical ? `; a round takes about ${p.typical} minutes` : '') + '.';
  if (p.skipped) text += ` ${p.skipped} ${p.skipped === 1 ? 'slot was' : 'slots were'} skipped because the last round was still working.`;
  if (p.too_slow) text += ' A round takes longer than the interval, so rounds follow each other without a pause: raise the interval or use a faster model.';
  return text;
}

export function renderRound(d) {
  const card = $('round'); if (!card) return;
  const r = d.round;
  card.style.display = r ? '' : 'none';
  if (!r || !changed('round', [r, d.pace])) return;
  $('roundNote').textContent = heading(r);
  const table = $('roundTable'); table.replaceChildren();
  table.append(el('tr', {}, ...['Pair', 'Status', 'The 11 agents, in order', 'Working on', 'Time', 'Tokens', 'The call'].map((h, i) =>
    el('th', {class: i >= 4 && i <= 5 ? 'n' : ''}, h))));
  r.rows.forEach(row => {
    const [label, kind] = STATUS[row.status];
    const steps = el('span', {class: 'steps'}, ...row.steps.map((s, i) => el('i', {class: s, title: r.stages[i]})));
    const call = row.rating ? el('b', {}, plainCall(row.rating)[0]) : el('span', {class: 'empty'}, '-');
    table.append(el('tr', {}, el('td', {}, el('b', {}, row.ticker)), el('td', {}, el('span', {class: 'badge ' + kind}, label)), el('td', {}, steps),
      el('td', {class: row.status === 'paused' ? 'bad' : ''}, row.status === 'paused' ? `quiet for ${time(row.quiet)}` : row.now || '-'),
      el('td', {class: 'n'}, row.status === 'waiting' ? '-' : time(row.seconds)), el('td', {class: 'n'}, row.tokens ? tokens(row.tokens) : '-'), el('td', {}, call)));
  });
  $('roundHow').textContent = r.parallel
    ? 'This model works on all the pairs at the same time, so every pair is "working" together and the whole round takes about as long as one pair.'
    : 'This model runs on your computer and does one pair at a time, so the pairs finish one after another.';
  $('roundHow').textContent += paceText(d.pace);
}
