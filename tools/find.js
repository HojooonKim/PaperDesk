// In-page helper: rectangles of regex matches in a page's text layer, matching across span boundaries.
window.__find = (pageNo, pattern) => {
  const pageEl = document.querySelectorAll('.page')[pageNo - 1];
  const nodes = [], starts = [];
  let text = '';
  const walker = document.createTreeWalker(pageEl.querySelector('.textLayer'), NodeFilter.SHOW_TEXT);
  for (let n; (n = walker.nextNode());) { starts.push(text.length); nodes.push(n); text += n.data; }
  const at = i => { let k = starts.length - 1; while (k > 0 && starts[k] > i) k--; return [nodes[k], i - starts[k]]; };
  const out = [];
  for (const m of text.matchAll(new RegExp(pattern, 'g'))) {
    const r = document.createRange();
    r.setStart(...at(m.index)); r.setEnd(...at(m.index + m[0].length - 1)); r.setEnd(r.endContainer, r.endOffset + 1);
    const b = r.getBoundingClientRect();
    if (b.width && b.height < 40 && b.top > 60 && b.bottom < innerHeight - 10) out.push({ text: m[0], x: b.left + b.width / 2, y: b.top + b.height / 2, left: b.left, right: b.right });
  }
  return out;
};
// A drawn pointer: headless screenshots have no mouse cursor.
window.__cursor = (x, y) => {
  let c = document.getElementById('__cursor');
  if (!c) {
    c = document.createElement('div');
    c.id = '__cursor';
    c.style.cssText = 'position:fixed;left:0;top:0;width:24px;height:24px;z-index:2147483647;pointer-events:none';
    c.innerHTML = '<svg width="24" height="24" viewBox="0 0 24 24"><path d="M3 2 L3 19 L7.5 14.8 L10.6 21.4 L13.4 20.2 L10.3 13.7 L16.4 13.7 Z" fill="#fff" stroke="#111" stroke-width="1.4" stroke-linejoin="round"/></svg>';
    document.documentElement.appendChild(c);
  }
  c.style.transform = `translate(${x - 3}px, ${y - 2}px)`;
};
// Select the first part (0..1) of a regex match in a page's text layer; returns the pointer position at its end.
window.__select = (pageNo, pattern, fraction) => {
  const pageEl = document.querySelectorAll('.page')[pageNo - 1];
  const nodes = [], starts = [];
  let text = '';
  const walker = document.createTreeWalker(pageEl.querySelector('.textLayer'), NodeFilter.SHOW_TEXT);
  for (let n; (n = walker.nextNode());) { starts.push(text.length); nodes.push(n); text += n.data; }
  const at = i => { let k = starts.length - 1; while (k > 0 && starts[k] > i) k--; return [nodes[k], i - starts[k]]; };
  const m = new RegExp(pattern).exec(text);
  const end = m.index + Math.max(1, Math.round(m[0].length * fraction));
  const [a, ao] = at(m.index), [b, bo] = at(end - 1);
  getSelection().setBaseAndExtent(a, ao, b, bo + 1);
  const rects = getSelection().getRangeAt(0).getClientRects(), last = rects[rects.length - 1];
  return { x: last.right, y: last.top + last.height / 2 };
};
