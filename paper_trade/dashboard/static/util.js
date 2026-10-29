// Small helpers shared by every part of the page.
export const $ = id => document.getElementById(id);
export const RATING = {Buy: 'var(--buy)', Overweight: 'var(--over)', Hold: 'var(--hold)', Underweight: 'var(--under)', Sell: 'var(--sell)'};

// Plain words for a model's call, and what it does to the account. Hold is NOT "waiting to buy or sell": it does nothing.
export function plainCall(rating, openNow) {
  if (rating === 'Buy') return ['BUY', 'BUY: opens a LONG trade. It makes money if the price rises.'];
  if (rating === 'Overweight') return ['BUY (mild)', 'A mild buy call. It leans up. In the fixed-lot account it counts as Buy and opens a LONG trade.'];
  if (rating === 'Sell') return ['SELL', 'SELL: opens a SHORT trade. It makes money if the price falls. A long trade that is open is closed first.'];
  if (rating === 'Underweight') return ['SELL (mild)', 'A mild sell call. It leans down. In the fixed-lot account it counts as Sell and opens a SHORT trade.'];
  return openNow
    ? ['KEEP OPEN', 'HOLD means do nothing. No new trade is made, and the trade that is already open stays open until its stop-loss or take-profit is hit. It does not mean waiting to buy or sell.']
    : ['NO TRADE', 'HOLD means do nothing. No trade is opened. It does not mean waiting to buy or sell: the model sees no clear direction right now.'];
}

export const money = (n, sign) => { const r = Math.round(n * 100) / 100; return (sign && r > 0 ? '+' : r < 0 ? '-' : '') + '$' + Math.abs(r).toFixed(2); };
export const cls = n => n >= 0.005 ? 'good' : n <= -0.005 ? 'bad' : '';
export const hhmm = t => new Date(t * 1000).toLocaleTimeString([], {hour12: false});
export const mins = s => s == null ? '-' : s >= 3600 ? (s / 3600).toFixed(1) + ' h' : Math.round(s / 60) + ' min';
export const fmtMs = ms => ms == null ? '-' : Math.round(ms).toLocaleString() + ' ms';
export const speed = ms => ms < 5000 ? 'fast' : ms < 30000 ? 'ok' : 'slow';          // same 30 s limit as the server's "slow replies"
export const eventMs = e => e.ms != null ? e.ms : Math.round((e.seconds || 0) * 1000); // older events only have seconds
// A time with minutes ("2026-10-28 14:15") is UTC, whatever clock the viewer's computer shows; a plain date is left as it is.
export const utc = s => typeof s === 'string' && s.length === 16 ? s + ' UTC' : s;
// A price with the usual number of decimals: 5 for forex-sized prices, 3 for yen-sized, 2 above 1000. A dash when there is none.
export const level = p => !p ? '-' : p >= 1000 ? p.toLocaleString(undefined, {maximumFractionDigits: 2}) : p >= 10 ? p.toFixed(3) : p.toFixed(5);
export const price = p => p >= 1000 ? p.toLocaleString(undefined, {maximumFractionDigits: 2}) : p >= 10 ? p.toFixed(2) : p.toFixed(4);

// Build a DOM node. Text goes in as text, never as HTML, so model or news text can never inject markup.
export function el(tag, props, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) k === 'class' ? e.className = v : k === 'style' ? e.style.cssText = v : e.setAttribute(k, v);
  for (const k of kids) e.append(k);
  return e;
}

// True when `value` differs from what was last shown under `key`. Lets a panel redraw only when its data changed,
// so the once-a-second push does not make everything flicker or reset what you are looking at.
const shownBefore = new Map();
export function changed(key, value) {
  const now = JSON.stringify(value);
  if (shownBefore.get(key) === now) return false;
  shownBefore.set(key, now);
  return true;
}

// Briefly colour an element green (went up), red (went down) or blue (changed), then let it fade.
export function flash(node, direction) {
  const name = direction > 0 ? 'flash-up' : direction < 0 ? 'flash-down' : 'flash';
  node.classList.remove('flash-up', 'flash-down', 'flash');
  void node.offsetWidth;                                  // restart the animation if it is still running
  node.classList.add(name);
}

// Small, safe markdown: **bold**, `code`, headings, bullet and numbered lists. Text only, never HTML.
export function md(text) {
  const root = el('div', {class: 'md'});
  let list = null;
  const inline = (parent, s) => {
    const re = /(\*\*[^*]+\*\*|`[^`]+`)/g; let last = 0, m;
    while ((m = re.exec(s))) {
      if (m.index > last) parent.append(s.slice(last, m.index));
      parent.append(m[0].startsWith('**') ? el('strong', {}, m[0].slice(2, -2)) : el('code', {}, m[0].slice(1, -1)));
      last = m.index + m[0].length;
    }
    if (last < s.length) parent.append(s.slice(last));
  };
  for (const raw of text.split('\n')) {
    const line = raw.replace(/\s+$/, ''); let m;
    if (!line.trim()) { list = null; continue; }
    if ((m = line.match(/^#{1,6}\s+(.*)$/))) { list = null; const h = el('div', {class: 'mh'}); inline(h, m[1]); root.append(h); }
    else if ((m = line.match(/^\s*(?:[-*•]|\d+[.)])\s+(.*)$/))) { if (!list) { list = el('ul', {}); root.append(list); } const li = el('li', {}); inline(li, m[1]); list.append(li); }
    else { list = null; const p = el('p', {}); inline(p, line); root.append(p); }
  }
  return root;
}
