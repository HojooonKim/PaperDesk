// Run with Playwright, or set PAPERDESK_PLAYWRIGHT_MODULE and PAPERDESK_CHROMIUM.
const { chromium } = require(process.env.PAPERDESK_PLAYWRIGHT_MODULE || 'playwright');
const { spawn } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const assert = require('node:assert/strict');

const project = path.resolve(__dirname, '../..');
const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'pd-translated-page-'));
const pdfPath = path.join(temp, 'test.pdf');
const figure = { ref: 'figure', kind: 'figure', text: '', rect: [.117, .123, .413, .243], captions: ['caption'] };
const caption = { ref: 'caption', kind: 'caption', text: 'Figure 1. Color sample.', rect: [.116, .25, .46, .275], captions: [] };
const body = { ref: 'body', kind: 'paragraph', text: 'See Figure 1 and citation [1].', rect: [.116, .314, .55, .337], captions: [] };
const untranslated = { ref: 'untranslated', kind: 'paragraph', text: 'This paragraph cites [2] in the original language.', rect: [.116, .382, .7, .408], captions: [] };

function writeFixture() {
  // A colored PDF drawing above two separate paragraphs and a caption.
  const text = [caption, body, untranslated].map((item, i) =>
    `BT /F1 14 Tf 72 ${[579, 530, 475][i]} Td (${item.text}) Tj ET`);
  const bibliography = ['References', '[1] Kim. Translated citation. 2020.', '[2] Lee. Original citation. 2021.', '[3] Park. Another study. 2022.'];
  const stream = ['0 0.5 1 rg 72 600 180 94 re f', '0 0 0 rg', ...text,
    ...bibliography.map((line, i) => `BT /F1 14 Tf 72 ${390 - 24 * i} Td (${line}) Tj ET`)].join('\n');
  const objects = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>',
    `<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`,
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
  ];
  let pdf = '%PDF-1.4\n';
  const offsets = objects.map((object, index) => {
    const offset = pdf.length;
    pdf += `${index + 1} 0 obj\n${object}\nendobj\n`;
    return offset;
  });
  const xref = pdf.length;
  pdf += ['xref', '0 6', '0000000000 65535 f ', ...offsets.map(n => `${String(n).padStart(10, '0')} 00000 n `),
    'trailer', '<< /Size 6 /Root 1 0 R >>', 'startxref', xref, '%%EOF', ''].join('\n');
  fs.writeFileSync(pdfPath, pdf);
}

writeFixture();
const child = spawn(process.env.PYTHON || 'python3', ['-m', 'tests.offline_server', path.join(temp, 'library')], {
  cwd: project,
  env: { ...process.env, PYTHONPATH: ['src', '.'].join(path.delimiter), PAPERDESK_TEST_PDF: pdfPath },
});
let browser;
(async () => {
  const url = await new Promise((resolve, reject) => {
    let output = '';
    child.stdout.on('data', data => {
      output += data;
      if (output.includes('\n')) resolve(JSON.parse(output.split('\n')[0]).url);
    });
    child.stderr.on('data', data => process.stderr.write(data));
    child.on('error', reject);
    child.on('exit', code => reject(new Error(`Test server exited with code ${code}`)));
  });
  browser = await chromium.launch(process.env.PAPERDESK_CHROMIUM ? { executablePath: process.env.PAPERDESK_CHROMIUM } : {});
  const page = await browser.newPage({ viewport: { width: 1540, height: 1000 }, colorScheme: 'dark' });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  // Supply stable Docling coordinates while using the real PDF, local server, and translation queue.
  await page.route('**/api/documents/*/analysis', route => route.fulfill({ json: { state: 'completed', layout: {
    pages: [{ number: 1, width: 612, height: 792, blocks: [figure, caption, body, untranslated] }],
  } } }));
  const settings = await page.request.put(url + 'api/settings', {
    headers: { 'X-Paperdesk': '1' }, data: { auto_translate: false, auto_info: false, auto_organize: false },
  });
  assert(settings.ok(), await settings.text());
  const library = await (await page.request.get(url + 'api/library')).json();
  const id = library.documents.find(doc => doc.filename === 'paper.pdf').id;
  await page.goto(url + 'reader?id=' + id);
  await page.waitForFunction(() => window.paperdesk?.view?.pages[0]?.map && window.paperdesk.view.translation.language);

  async function mode(name) {
    await page.getByTitle('Translate paper', { exact: true }).click();
    await page.getByRole('menuitem', { name, exact: true }).click();
  }

  const row = page.locator('.page-row').first();
  const original = row.locator('.page');
  const translated = row.locator('.translated-page');
  async function checkPreviews() {
    await translated.locator('.xref[data-kind=cite]').hover();
    await page.locator('.cite-pop .cite-text').filter({ hasText: 'Kim. Translated citation.' }).waitFor({ timeout: 4000 });
    // The untranslated citation is painted into the copied canvas, with no link element.
    const point = await translated.evaluate(el => {
      const hit = window.paperdesk.view.pages[0].hotspots.find(spot => spot.label === '[2]').rects[0];
      const box = el.getBoundingClientRect();
      return { x: box.left + (hit.left + hit.right) * box.width / 2, y: box.top + (hit.top + hit.bottom) * box.height / 2 };
    });
    await page.mouse.move(point.x, point.y);
    await page.locator('.cite-pop .cite-text').filter({ hasText: 'Lee. Original citation.' }).waitFor({ timeout: 4000 });
    await page.mouse.move(0, 0);
    await page.locator('.cite-pop').waitFor({ state: 'hidden' });
  }
  await mode('Original and translated pages');
  await original.waitFor({ state: 'visible' });
  await translated.waitFor({ state: 'visible' });
  const paragraphs = translated.locator('.page-translation');
  assert.equal(await paragraphs.count(), 0, 'The untranslated page should still show the source PDF');

  await page.evaluate(async () => {
    const reader = window.paperdesk.view;
    await reader.translation.enqueue(reader.analysis.blocks.filter(block => ['body', 'caption'].includes(block.sourceRef)));
  });
  await translated.getByText('[demo] ' + body.text, { exact: true }).waitFor();
  assert.match((await translated.innerText()).replace(/\s+/g, ' '), /\[demo\] Figure 1\. Color sample\./);
  assert.equal(await paragraphs.count(), 2, 'Only translated regions should cover the copied page');
  assert(await original.getByText(body.text, { exact: true }).count(), 'The original text remains available');

  const pair = await row.evaluate(element => {
    const left = element.querySelector('.page'), right = element.querySelector('.translated-page');
    function figureColor(page) {
      const canvas = page.querySelector('canvas');
      return [...canvas.getContext('2d').getImageData(Math.floor(canvas.width * .23), Math.floor(canvas.height * .18), 1, 1).data];
    }
    return { left: left.getBoundingClientRect().toJSON(), right: right.getBoundingClientRect().toJSON(),
      sourceFigure: figureColor(left), translatedFigure: figureColor(right) };
  });
  assert(pair.left.right <= pair.right.left, 'The original and translation should be side by side');
  assert.equal(pair.left.top, pair.right.top, 'The two pages should scroll in the same row');
  assert.equal(pair.left.width, pair.right.width, 'The two pages should use the same scale');
  assert(pair.sourceFigure[0] < 30 && pair.sourceFigure[2] > 220, `Expected the colored figure: ${pair.sourceFigure}`);
  assert.deepEqual(pair.translatedFigure, pair.sourceFigure, 'The translated page should preserve the original figure');
  if (process.env.PAPERDESK_TEST_SCREENSHOT) await page.screenshot({ path: process.env.PAPERDESK_TEST_SCREENSHOT });
  await checkPreviews();

  const [save] = await Promise.all([
    page.waitForResponse(response => response.url() === url + 'api/preferences' && response.request().method() === 'PATCH'),
    page.locator('button[data-mode=translated]').click(),
  ]);
  assert(save.ok(), await save.text());
  await original.waitFor({ state: 'hidden' });
  await translated.getByText('[demo] ' + body.text, { exact: true }).waitFor();
  const prefs = await page.request.get(url + 'api/preferences');
  assert.equal((await prefs.json()).preferences.translation_mode, 'translated');
  await page.reload();
  await translated.getByText('[demo] ' + body.text, { exact: true }).waitFor();
  assert.equal(await original.isVisible(), false);
  await checkPreviews();
  const fontFamily = () => paragraphs.first().evaluate(el => getComputedStyle(el).fontFamily);
  assert.match(await fontFamily(), /Apple SD Gothic Neo/);
  await page.goto(url + 'settings');
  const font = page.getByLabel('Translation font');
  assert.equal(await font.inputValue(), 'sans');
  const [fontSave] = await Promise.all([
    page.waitForResponse(response => response.url() === url + 'api/preferences' && response.request().method() === 'PATCH'),
    font.selectOption('serif'),
  ]);
  assert(fontSave.ok(), await fontSave.text());
  await page.goto(url + 'reader?id=' + id);
  await paragraphs.first().waitFor();
  assert.match(await fontFamily(), /Georgia/);
  await page.locator('button[data-mode=compare]').click();
  await original.waitFor({ state: 'visible' });
  await translated.getByText('[demo] ' + body.text, { exact: true }).waitFor();
  assert.deepEqual(errors, []);
  console.log('Translated page: paired view, figure retention, partial translation, reference previews, saved mode and font passed');
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(async () => {
  await browser?.close();
  child.kill();
});
