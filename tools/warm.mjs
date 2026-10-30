// Open the paper so the app analyses it and queues automatic translation for the current target language.
import { open, sleep } from './lib.mjs';
const [base, docId, outDir] = process.argv.slice(2);
const api = path => fetch(base + path, { headers: { 'X-Paperdesk': '1' } }).then(r => r.json());
const page = await open({ profile: outDir + '/profile-warm' });
try {
  await page.go(base + 'reader?id=' + docId, 4000);
  const start = Date.now();
  for (;;) {
    const analysis = await api(`api/documents/${docId}/analysis`);
    const jobs = await api(`api/documents/${docId}/translation-jobs`);
    const list = jobs.jobs || jobs;
    console.log(Math.round((Date.now() - start) / 1000) + 's', analysis.state, JSON.stringify(list.map(j => [j.state, j.done, j.total, j.payload && j.payload.language])));
    if (list.some(j => ['running', 'queued', 'completed'].includes(j.state))) break;
    if (Date.now() - start > 600000) throw new Error('no translation job after 10 minutes');
    await sleep(5000);
  }
  console.log('title:', (await api(`api/documents/${docId}`)).document.title);
  console.log('errors:', JSON.stringify(page.errors));
} finally { page.close(); }
