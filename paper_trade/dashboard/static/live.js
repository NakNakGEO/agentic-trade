// Live connection to the server: pushed updates, a visible "how fresh is this" indicator, never a silent freeze.
import {$} from './util.js';

const FRESH = 6, STALE = 12;          // seconds: fine up to FRESH, amber up to STALE, red beyond
let lastAt = 0, down = false;

function paint() {
  const pill = $('live'), age = lastAt ? (Date.now() - lastAt) / 1000 : null;
  if (down) { pill.className = 'pill slow'; pill.textContent = '● reconnecting...'; }
  else if (age === null) { pill.className = 'pill'; pill.textContent = '● connecting...'; }
  else if (age > STALE) { pill.className = 'pill slow'; pill.textContent = `● no update for ${Math.round(age)} s`; }
  else if (age > FRESH) { pill.className = 'pill ok'; pill.textContent = `● live · ${Math.round(age)} s ago`; }
  else { pill.className = 'pill fast live'; pill.textContent = `● LIVE · ${Math.round(age)} s ago`; }
}

// Calls onState(state) every time the server pushes a new one. EventSource reconnects by itself.
export function startStream(run, mode, onState) {
  setInterval(paint, 1000);
  const query = 'run=' + encodeURIComponent(run) + '&mode=' + encodeURIComponent(mode);
  if (!window.EventSource) return poll(query, onState);
  const source = new EventSource('/api/stream?' + query);
  source.addEventListener('state', e => {
    const msg = JSON.parse(e.data);
    down = false; lastAt = Date.now();
    if (msg.ok) onState(msg.data); else $('live').title = msg.error;
    paint();
  });
  source.onerror = () => { down = true; paint(); };
}

async function poll(query, onState) {               // very old browsers only
  for (;;) {
    try {
      const msg = await (await fetch('/api/state?' + query, {cache: 'no-store'})).json();
      down = false; lastAt = Date.now(); if (msg.ok) onState(msg.data);
    } catch (e) { down = true; }
    paint();
    await new Promise(r => setTimeout(r, 3000));
  }
}
