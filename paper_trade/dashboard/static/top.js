// Run name, status, progress bar, current agent chips, and the "last reply" lag pill.
import {$, el, fmtMs, mins, speed, flash} from './util.js';

let lastProgress = '';

export function renderTop(d) {
  $('run').textContent = '· ' + d.run_id;
  const status = $('status'); status.textContent = d.running ? 'running' : 'idle'; status.className = 'pill' + (d.running ? ' on' : '');
  const lag = $('lag'), last = d.tokens && d.tokens.ms_last;               // is the model keeping up? latest reply time
  if (last == null) lag.style.display = 'none';
  else { lag.style.display = ''; lag.textContent = `last reply ${fmtMs(last)}`; lag.className = 'pill ' + speed(last); }

  const done = d.cells_done, total = d.cells_total || 0;
  $('progress').style.width = (total ? Math.min(100, done / total * 100) : 0) + '%';
  const text = total ? `${done} of ${total} decisions done` : (done ? `${done} decisions` : 'no run yet');
  $('progressText').textContent = text;
  if (lastProgress && text !== lastProgress) flash($('progressText'), 0);  // a decision just landed
  lastProgress = text;

  const left = d.seconds_per_cell && total && d.running ? d.seconds_per_cell * (total - done) : null;
  $('eta').textContent = d.elapsed_seconds == null ? '' : `elapsed ${mins(d.elapsed_seconds)}`
    + (d.seconds_per_cell ? ` · ${mins(d.seconds_per_cell)} per decision` : '') + (left ? ` · about ${mins(left)} left (rough)` : '');

  const cell = d.current_cell;
  $('nowLine').textContent = cell ? `· now: ${cell}` + (d.current_node ? ' · ' + d.current_node : '') : '';
  const seen = [], generic = ['-', 'agent', 'tools'];                       // generic names come from older events
  for (const e of d.feed) if (e.cell === cell && e.node && !generic.includes(e.node) && !seen.includes(e.node)) seen.push(e.node);
  const stages = $('stages'); stages.replaceChildren();
  seen.forEach(n => stages.append(el('span', {class: 'stage ' + (n === d.current_node && d.running ? 'now' : 'done')}, n)));
}
