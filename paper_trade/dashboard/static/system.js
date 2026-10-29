// Which model is answering, how much it has used, and how fast it replies. Local runs also show the GPU.
import {$, el, fmtMs, mins, speed, changed} from './util.js';

const n = v => (v || 0).toLocaleString();
const line = (k, v) => el('div', {class: 'row', style: 'font-size:13px'}, el('span', {}, k), el('span', {style: 'color:var(--ink)'}, v));
const meter = (label, value, text) => el('div', {class: 'meter'}, el('div', {class: 'bar'}, el('i', {style: `width:${value}%`})),
  el('div', {class: 'row'}, el('span', {}, label), el('span', {}, text)));
const section = (title, ...kids) => el('div', {}, el('h2', {}, title), ...kids);
const latency = (k, ms) => el('div', {class: 'row', style: 'font-size:13px'}, el('span', {}, k),
  el('span', {class: 'lat ' + (ms == null ? '' : speed(ms))}, fmtMs(ms)));

function modelSection(d) {
  const s = d.system, g = s.gpu || {}, o = s.ollama || {}, t = d.tokens || {};
  const used = (t.tokens_in || 0) + (t.tokens_out || 0);
  const thinking = s.thinking === false ? '  (thinking off)'
    : s.thinking ? `  (thinking on${s.effort ? ', ' + s.effort + ' effort' : ''})` : '';
  const rows = [el('div', {}, el('b', {}, s.model || '-'), el('span', {style: 'color:var(--mute)'}, thinking)),
    el('div', {style: 'color:var(--mute);font-size:12px;margin-top:4px'}, s.provider_label)];
  if (s.local) {                                  // GPU and local-model readings only make sense for a local run
    if (g.name) rows.push(el('div', {style: 'color:var(--mute);font-size:12px'}, g.name), meter('GPU busy', g.util, g.util + '%'),
      meter('GPU memory', g.mem_used_mb / g.mem_total_mb * 100, `${(g.mem_used_mb / 1024).toFixed(1)} of ${(g.mem_total_mb / 1024).toFixed(1)} GB`));
    rows.push(line('Generation speed', o.tokens_per_second ? o.tokens_per_second.toFixed(0) + ' tokens/s' : '-'),
      line('Last prompt', o.last_prompt_tokens ? n(o.last_prompt_tokens) + ' tokens' : '-'));
  } else if (s.monthly_tokens) {
    rows.push(meter('Free monthly allowance, used by this run', Math.min(100, used / s.monthly_tokens * 100),
      `${(used / 1e6).toFixed(2)}M of ${(s.monthly_tokens / 1e6).toFixed(0)}M tokens`));
  }
  rows.push(line('Planned assets', (d.meta.tickers || []).join(', ') || '-'));
  return section(s.local ? 'Model and machine' : 'Model', ...rows);
}

function tokenSections(d) {
  const t = d.tokens || {}, local = d.system.local;
  if (!t.calls) return [];
  const rows = [el('div', {class: 'tile'}, el('b', {}, n(t.tokens_in + t.tokens_out)), el('span', {}, 'tokens in total, since the live feed began')),
    line('Read (prompts)', n(t.tokens_in)), line('Written (answers)', n(t.tokens_out)),
    line('Model calls / tool calls', `${n(t.calls)} / ${n(t.tool_calls)}`),
    line('Average per call', n(Math.round((t.tokens_in + t.tokens_out) / t.calls))),
    line('Time spent generating', mins(t.llm_seconds)),
    latency('Last response', t.ms_last), latency('Average response', t.ms_avg),
    latency('Typical (median) response', t.ms_median), latency('Slowest response', t.ms_max),
    line('Slow replies (30 s or more)', `${n(t.slow_calls)} of ${n(t.calls)}`)];
  if (t.errors) rows.push(line('Model errors', n(t.errors)));
  const table = el('table', {style: 'font-size:12px'}, el('tr', {}, el('th', {}, 'Agent'), el('th', {class: 'n'}, 'Calls'), el('th', {class: 'n'}, 'Tokens')));
  t.by_node.forEach(r => table.append(el('tr', {}, el('td', {}, r.node), el('td', {class: 'n'}, n(r.calls)), el('td', {class: 'n'}, n(r.tokens)))));
  return [section(local ? 'Tokens used (local, no API cost)' : 'Tokens used by this run', ...rows), section('Tokens by agent', table)];
}

export function renderSystem(d) {
  if (!changed('system', [d.system, d.tokens, d.meta.tickers])) return;
  $('system').replaceChildren(modelSection(d), ...tokenSections(d));
}
