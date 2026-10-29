// Live agent feed: new messages are added on top and old ones are left alone, so reading is never interrupted.
import {$, el, md, hhmm, fmtMs, speed, eventMs} from './util.js';

const shown = new Set();
const keyOf = e => `${e.t}|${e.node}|${e.kind}|${(e.text || '').length}`;
const hueOf = s => { let h = 0; for (const c of s) h = (h * 31 + c.charCodeAt(0)) % 360; return h; };

function eventCard(e) {
  const card = el('div', {class: 'ev ' + (e.kind === 'tool' ? 'tool' : e.kind === 'error' ? 'err' : 'llm'),
    style: `--hue:hsl(${hueOf(e.node || '-')} 60% 52%)`});
  const isCall = e.kind === 'llm' || e.kind === 'error', ms = isCall ? eventMs(e) : null;
  const meta = e.kind === 'llm' && e.tokens_out ? `${e.tokens_out} tokens written` : '';
  card.append(el('div', {class: 'head'}, el('span', {class: 'node'}, e.node || '-'), el('time', {}, hhmm(e.t)),
    isCall ? el('span', {class: 'lat ' + speed(ms), title: 'Response time of this model call'}, fmtMs(ms)) : '',
    el('span', {class: 'meta'}, [e.cell, meta].filter(Boolean).join(' · '))));
  const body = el('div', {class: 'body'});
  if (e.kind === 'tool') body.append(`tool call: ${e.tool}(${e.text})`);
  else if (e.kind === 'error') { body.style.color = 'var(--bad)'; body.append('error: ' + e.text); }
  else {
    if (e.tool_calls && e.tool_calls.length) body.append(el('p', {class: 'meta'}, 'asks for tools: ' + e.tool_calls.join(', ')));
    if (e.text) body.append(md(e.text));
  }
  card.append(body);
  return card;
}

export function renderFeed(d) {
  const box = $('feed'), scrolledDown = box.scrollTop > 40, before = box.scrollHeight;
  const fresh = d.feed.filter(e => !shown.has(keyOf(e)));
  if (fresh.length) { const empty = $('feedEmpty'); if (empty) empty.remove(); }
  fresh.forEach(e => { shown.add(keyOf(e)); box.prepend(eventCard(e)); });
  while (box.children.length > 300) box.lastChild.remove();
  if (!box.children.length && !$('feedEmpty')) box.append(el('div', {id: 'feedEmpty', class: 'empty'}, 'No agent activity yet. Start a run to see the agents work here.'));
  if (scrolledDown && fresh.length) box.scrollTop += box.scrollHeight - before;     // keep the message being read in place
}

$('showTools').addEventListener('change', e => $('feed').classList.toggle('hide-tools', !e.target.checked));
