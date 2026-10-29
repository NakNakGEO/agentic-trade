// Starts the page: picks the run, opens the live stream, and hands every pushed state to the panels.
import {$, el} from './util.js';
import {startStream} from './live.js';
import {renderTop} from './top.js';
import {renderFeed} from './feed.js';
import {renderSystem} from './system.js';
import {renderDecisions} from './decisions.js';
import {renderPortfolio, updateLive} from './portfolio.js';
import {renderBlotter, updateBlotterLive} from './blotter.js';
import {renderRound} from './round.js';
import {renderScorecard} from './scorecard.js';
import {startMarket, onQuotes} from './market.js';
import {renderPicker, reload as reloadChart} from './tradechart.js';
import {showTradingView} from './tvwidget.js';

const params = new URLSearchParams(location.search);
window.addEventListener('instrument', e => showTradingView(e.detail, $('tvChart')));

// No run in the address means "open the most recently active one".
async function loadRuns() {
  let runs = [];
  try { const msg = await (await fetch('/api/runs', {cache: 'no-store'})).json(); if (msg.ok) runs = msg.data; } catch (e) { /* keep the last list */ }
  if (!params.get('run') && runs.length) { params.set('run', runs[0].run); history.replaceState(null, '', '?' + params); }
  const current = params.get('run'), box = $('runPicker');
  const key = JSON.stringify(runs.map(r => [r.run, r.decisions])) + current;
  if (box.dataset.key === key) return;                       // rebuild only on change, so an open menu is not disturbed
  box.dataset.key = key; box.replaceChildren();
  runs.forEach(r => {
    const where = r.provider === 'ollama' ? 'local' : 'online API';
    const option = el('option', {value: r.run}, `${r.run} · ${r.model || '?'} (${where}) · ${r.decisions}/${r.planned || '?'} decisions`);
    if (r.run === current) option.selected = true;
    box.append(option);
  });
  if (current && !runs.some(r => r.run === current)) box.append(el('option', {value: current, selected: 'selected'}, current));
}

$('runPicker').addEventListener('change', e => { params.set('run', e.target.value); location.search = params.toString(); });

// Account rules: the same decisions traded long and short (default) or long only.
const mode = ['long_only', 'full_size', 'fixed_lot'].includes(params.get('mode')) ? params.get('mode') : 'fixed_lot';
$('modePicker').value = mode;
$('modePicker').addEventListener('change', e => { params.set('mode', e.target.value); location.search = params.toString(); });

function showAll(d) {
  renderTop(d); renderRound(d); renderScorecard(d); renderFeed(d); renderSystem(d); renderDecisions(d); renderPortfolio(d); renderBlotter(d); renderPicker(d);
}

loadRuns().then(() => {
  onQuotes(() => { updateLive(); updateBlotterLive(); });           // every new price re-values the paper positions
  startMarket();
  startStream(params.get('run') || '', mode, showAll);
  setInterval(reloadChart, 60000);
  setInterval(loadRuns, 20000);
});
