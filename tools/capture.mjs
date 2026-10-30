// README demo capture: screenshots and GIFs for one UI language, from the temporary demo library.
// node capture.mjs <base> <docId> <outDir> <ui-lang> <target-language> [scroll,preview,ask,hero,dark]
import fs from 'node:fs';
import { execFileSync } from 'node:child_process';
import { open, sleep } from './lib.mjs';

const [base, docId, outDir, lang, target, what = 'scroll,preview,ask,hero,dark'] = process.argv.slice(2);
const want = name => what.split(',').includes(name);
const FIND = fs.readFileSync(new URL('./find.js', import.meta.url), 'utf8');
const api = (path, method = 'GET', body) => fetch(base + path, { method, headers: { 'X-Paperdesk': '1', 'Content-Type': 'application/json' },
  body: body && JSON.stringify(body) }).then(r => r.json());
fs.mkdirSync(outDir, { recursive: true });

await api('api/settings', 'PUT', { ui_language: lang, target_language: target });
await api('api/preferences', 'PATCH', { translation_mode: 'side', sidebar_width: 252, assistant_width: 380 });

async function reader(page, { theme = 'light', mode = 'side', wait = 7000 } = {}) {
  await page.send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-color-scheme', value: theme }] });
  await page.go(base + 'reader?id=' + docId, wait);
  await page.evaluate(`paperdesk.view.setTranslationMode(${JSON.stringify(mode)})`);
  await page.evaluate(FIND);
  await sleep(1500);
}

const rect = (page, selector) => page.evaluate(`(() => { const b = document.querySelector(${JSON.stringify(selector)}).getBoundingClientRect();
  return { x: Math.round(b.left), y: Math.round(b.top), width: Math.round(b.width), height: Math.round(b.height) }; })()`);

async function toPage(page, n, offset = 0) {
  await page.evaluate(`(() => { const v = paperdesk.view, el = document.querySelectorAll('.page')[${n - 1}];
    v.pagesEl.scrollTop += el.getBoundingClientRect().top - v.pagesEl.getBoundingClientRect().top - 12 + ${offset}; })()`);
  await sleep(1500);
}

// Hover targets the app itself uses: hotspots in the PDF, .xref links in translation cards.
const hotspot = (page, n, label) => page.evaluate(`(() => {
  const v = paperdesk.view, state = v.pages[${n - 1}], box = state.el.getBoundingClientRect();
  const spot = state.hotspots.find(s => ${JSON.stringify(label)} === (s.kind === 'visual' ? s.label : 'cite' + s.entries.length));
  const r = spot.rects[0], left = r.left ?? r[0], top = r.top ?? r[1], right = r.right ?? r[2], bottom = r.bottom ?? r[3];
  return { x: box.left + (left + right) / 2 * box.width, y: box.top + (top + bottom) / 2 * box.height };
})()`);
const xref = (page, n, text) => page.evaluate(`(() => {
  const el = [...document.querySelectorAll('.page-row[data-page="${n}"] .tcol .xref')].find(e => e.textContent.trim() === ${JSON.stringify(text)});
  const b = el.getBoundingClientRect(); return { x: b.left + b.width / 2, y: b.top + b.height / 2 };
})()`);

// Frames for a GIF: capture() grabs the clip once; hold(n) repeats the last frame.
function recorder(page, name, clip) {
  const dir = `${outDir}/frames-${name}`;
  fs.rmSync(dir, { recursive: true, force: true }); fs.mkdirSync(dir);
  let n = 0, last = null;
  return {
    async capture() {
      const s = await page.send('Page.captureScreenshot', { format: 'png', clip: { ...clip, scale: 1 } });
      last = `${dir}/f${String(n++).padStart(4, '0')}.png`;
      fs.writeFileSync(last, Buffer.from(s.result.data, 'base64'));
    },
    hold(count) { for (let i = 0; i < count; i++) fs.copyFileSync(last, `${dir}/f${String(n++).padStart(4, '0')}.png`); },
    gif(width, colors = 64) {
      const out = `${outDir}/${name}.gif`;
      execFileSync('ffmpeg', ['-y', '-loglevel', 'error', '-framerate', '10', '-i', `${dir}/f%04d.png`, '-vf',
        `scale=${width}:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=${colors}:stats_mode=diff[p];[b][p]paletteuse=dither=none:diff_mode=rectangle`, out]);
      return `${out} ${Math.round(fs.statSync(out).size / 1024)} KB, ${n} frames`;
    },
  };
}

async function move(page, x, y, extra = {}) {
  await page.mouse('mouseMoved', x, y, extra);
  await page.evaluate(`__cursor(${x}, ${y})`);
}

async function glide(page, from, to, steps, rec) {
  for (let i = 1; i <= steps; i++) {
    await move(page, from.x + (to.x - from.x) * i / steps, from.y + (to.y - from.y) * i / steps);
    await sleep(35);
    if (rec) await rec.capture();
  }
  return to;
}

const report = {};
async function session(scale, body) {
  const page = await open({ profile: `${outDir}/profile-${lang}-${scale}-${Date.now()}`, scale });
  try { await body(page); } finally { report.errors = (report.errors || []).concat(page.errors); page.close(); }
}

await session(1, async page => {
  if (want('scroll')) {
    // The original and its translation scroll together, page by page.
    await reader(page);
    const main = await rect(page, '.main'), pdf = await rect(page, '.page');
    const rec = recorder(page, 'scroll', main), at = { x: pdf.x + pdf.width / 2, y: 520 };
    await move(page, at.x, at.y);
    await rec.capture(); rec.hold(10);
    for (let i = 0; i < 32; i++) { await page.wheel(at.x, at.y, 50); await sleep(70); await rec.capture(); }
    rec.hold(14);
    report.scroll = rec.gif(640, 48);
  }
  if (want('preview')) {
    // Hover a figure reference that points to another page, then a citation.
    await reader(page);
    await toPage(page, 5, 28);
    const main = await rect(page, '.main'), rec = recorder(page, 'preview', main);
    let at = { x: main.x + 330, y: main.y + 420 };
    await move(page, at.x, at.y);
    await rec.capture(); rec.hold(6);
    at = await glide(page, at, await hotspot(page, 5, 'Figure 2'), 12, rec);
    await page.until(`(() => { const i = document.querySelector('.cite-pop img'); return i && i.complete && i.naturalWidth > 0; })()`, 15000, 100);
    await sleep(300); await rec.capture(); rec.hold(28);
    at = await glide(page, at, { x: at.x + 30, y: at.y - 40 }, 4, rec);
    at = await glide(page, at, await hotspot(page, 5, 'cite3'), 12, rec);
    await page.until(`!!document.querySelector('.cite-pop:not(.visual)')`, 5000, 100);
    await sleep(300); await rec.capture(); rec.hold(30);
    report.preview = rec.gif(700, 64);
  }
  if (want('ask')) {
    // Select a sentence, choose Explain, read the answer in the assistant.
    await api(`api/documents/${docId}/conversation`, 'PUT', { turns: [] });
    await reader(page);
    const main = await rect(page, '.main');
    const clip = { x: 150, y: 0, width: 1290, height: 900 }, rec = recorder(page, 'ask', clip);  // the selection menu reaches left of the card
    const sentence = String.raw`The dominant sequence[\s\S]*?an encoder and a decoder\.`;
    const [start] = await page.evaluate(`__find(1, 'The dominant sequence')`);
    let at = { x: start.left + 60, y: start.y + 70 };
    await move(page, at.x, at.y);
    await rec.capture(); rec.hold(6);
    at = await glide(page, at, { x: start.left, y: start.y }, 8, rec);
    for (let i = 1; i <= 14; i++) {
      const end = await page.evaluate(`__select(1, ${JSON.stringify(sentence)}, ${i / 14})`);
      at = end; await move(page, at.x, at.y); await sleep(40); await rec.capture();
    }
    await page.until(`!!document.querySelector('.selection-menu')`, 3000, 100);
    await sleep(300); await rec.capture(); rec.hold(8);
    const button = await page.evaluate(`(() => { const b = document.querySelectorAll('.selection-menu button')[1].getBoundingClientRect(); return { x: b.left + b.width / 2, y: b.top + b.height / 2 }; })()`);
    at = await glide(page, at, button, 8, rec);
    rec.hold(4);
    await page.mouse('mousePressed', at.x, at.y); await page.mouse('mouseReleased', at.x, at.y);
    await move(page, at.x + 40, at.y + 30);
    for (let i = 0; i < 10; i++) { await sleep(150); await rec.capture(); }
    await page.until(`document.querySelector('.assistant .answer') && !document.querySelector('.assistant .typing')`, 180000, 500);
    await sleep(800); await rec.capture(); rec.hold(45);
    report.ask = rec.gif(900, 64);
  }
});

await session(2, async page => {
  if (want('hero')) {
    await reader(page);
    await page.shot(`${outDir}/reader.png`);
    report.hero = `${outDir}/reader.png`;
  }
  if (want('dark')) {
    await reader(page, { theme: 'dark', mode: 'over' });
    await toPage(page, 3);
    await page.shot(`${outDir}/dark-overlay.png`);
    report.dark = `${outDir}/dark-overlay.png`;
  }
});
console.log(JSON.stringify(report, null, 1));
