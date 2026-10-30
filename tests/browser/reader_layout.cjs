// Run with Playwright, or PAPERDESK_PLAYWRIGHT_MODULE; PAPERDESK_CHROMIUM selects an installed browser.
const { chromium } = require(process.env.PAPERDESK_PLAYWRIGHT_MODULE || 'playwright');
const { spawn } = require('child_process');
const fs = require('fs'), os = require('os'), path = require('path'), assert = require('assert/strict');
const project = path.resolve(__dirname, '../..');
const home = fs.mkdtempSync(path.join(os.tmpdir(), 'pd-reader-layout-'));
const server = spawn(process.env.PYTHON || 'python3', ['-m', 'tests.offline_server', home], {
  cwd: project, env: { ...process.env, PYTHONPATH: ['src', '.'].join(path.delimiter) }
});
let browser;
(async () => {
  const url = await new Promise((resolve, reject) => {
    let output = '';
    server.stdout.on('data', data => {
      output += data;
      if (output.includes('\n')) resolve(JSON.parse(output.split('\n')[0]).url);
    });
    server.stderr.on('data', data => process.stderr.write(data));
    server.on('error', reject);
    server.on('exit', code => reject(new Error('Test server exited: ' + code)));
  });
  browser = await chromium.launch(process.env.PAPERDESK_CHROMIUM ? { executablePath: process.env.PAPERDESK_CHROMIUM } : {});
  const page = await browser.newPage({ viewport: { width: 1200, height: 900 }, colorScheme: 'dark' });
  await page.goto(url);
  await page.waitForFunction(() => window.paperdesk?.settings?.data);
  const themes = await page.evaluate(() => {
    const results = [], root = document.documentElement;
    root.dataset.shell = 'native';
    for (const platform of ['other', 'mac']) for (const theme of ['light', 'dark', 'system']) {
      root.dataset.platform = platform;
      window.paperdeskTheme.set(theme);
      results.push({ platform, theme, scheme: getComputedStyle(root).colorScheme,
        backdrop: getComputedStyle(document.body).backgroundImage });
    }
    return results;
  });
  for (const theme of themes) {
    assert.equal(theme.scheme, theme.theme === 'light' ? 'light' : 'dark', JSON.stringify(theme));
    assert.equal(theme.backdrop === 'none', theme.platform === 'mac', JSON.stringify(theme));
  }
  // Exercise the real layout methods and CSS with stable page sizes, independent of PDF rasterization.
  const results = await page.evaluate(async () => {
    const { ReaderView } = await import('/js/reader.js');
    const results = [];
    for (const width of [560, 800, 1100]) for (const mode of ['hidden', 'overlay', 'side']) for (const zoom of [1, 2, 3]) {
      const root = document.createElement('div');
      root.style = `position:fixed;left:0;top:0;width:${width}px;height:600px;z-index:999;background:white`;
      root.innerHTML = '<div class="reader" style="height:600px"><div class="reader-body"><div class="pages"></div></div></div>';
      document.body.append(root);
      const reader = Object.create(ReaderView.prototype);
      Object.assign(reader, { readerEl: root.firstElementChild, pagesEl: root.querySelector('.pages'),
        zoom: 1, fitScale: 1, current: 1, tmode: mode, zoomLabel: document.createElement('span'),
        renderPage() {}, schedulePrerender() {} });
      reader.pages = Array.from({ length: 3 }, (_, i) => {
        const row = document.createElement('div'); row.className = 'page-row';
        const el = document.createElement('div'); el.className = 'page';
        const tcol = document.createElement('div'); tcol.className = 'tcol';
        row.append(el, tcol); reader.pagesEl.append(row);
        return { number: i + 1, size: { width: 600, height: 800 }, row, el, tcol };
      });
      reader.sizePages(); reader.setZoom(zoom);
      const viewport = reader.pagesEl.getBoundingClientRect();
      reader.pagesEl.scrollLeft = 0;
      const left = reader.pages[0].el.getBoundingClientRect().left - viewport.left;
      reader.pagesEl.scrollLeft = reader.pagesEl.scrollWidth;
      const last = mode === 'side' ? reader.pages[0].tcol : reader.pages[0].el;
      const right = last.getBoundingClientRect().right - viewport.left - reader.pagesEl.clientWidth;
      results.push({ width, mode, zoom, left, right });
      root.remove();
    }
    return results;
  });
  for (const result of results) {
    assert(result.left >= -1, 'Left edge is unreachable: ' + JSON.stringify(result));
    assert(result.right <= 1, 'Right edge is unreachable: ' + JSON.stringify(result));
  }
  console.log(`Reader layout: ${results.length} viewport/mode/zoom combinations passed`);
  console.log(`Native backdrop: ${themes.length} platform/theme combinations passed under a dark system theme`);
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(async () => {
  await browser?.close();
  server.kill();
});
