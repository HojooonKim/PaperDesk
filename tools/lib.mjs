// Headless Chrome over CDP with a throwaway profile (Node's built-in WebSocket).
import { spawn } from 'node:child_process';
import fs from 'node:fs';

export const sleep = ms => new Promise(r => setTimeout(r, ms));

export async function open({ profile, width = 1440, height = 900, scale = 1 }) {
  fs.rmSync(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
  const chrome = spawn('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', ['--headless=new', '--no-first-run',
    '--no-default-browser-check', '--hide-scrollbars', '--font-render-hinting=none', '--user-data-dir=' + profile,
    '--remote-debugging-port=0', 'about:blank'], { stdio: 'ignore' });
  let port;
  for (let i = 0; i < 100 && !port; i++) { try { port = fs.readFileSync(profile + '/DevToolsActivePort', 'utf8').split('\n')[0]; } catch { await sleep(100); } }
  const target = (await (await fetch(`http://127.0.0.1:${port}/json/list`)).json()).find(t => t.type === 'page');
  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise(r => ws.onopen = r);
  let id = 0;
  const waiting = new Map(), errors = [];
  ws.onmessage = e => {
    const m = JSON.parse(e.data);
    if (m.id && waiting.has(m.id)) { waiting.get(m.id)(m); waiting.delete(m.id); }
    if (m.method === 'Runtime.exceptionThrown') errors.push('exception: ' + m.params.exceptionDetails.text + ' ' + (m.params.exceptionDetails.exception || {}).description);
    if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') errors.push('console.error: ' + m.params.args.map(a => a.value || a.description).join(' '));
  };
  const send = (method, params = {}) => new Promise(r => { waiting.set(++id, r); ws.send(JSON.stringify({ id, method, params })); });
  const evaluate = async expr => {
    const m = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true });
    if (m.result.exceptionDetails) throw new Error(JSON.stringify(m.result.exceptionDetails).slice(0, 600));
    return m.result.result.value;
  };
  await send('Page.enable'); await send('Runtime.enable');
  await send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: scale, mobile: false });
  const page = {
    send, evaluate, errors,
    async go(url, wait = 2500) { await send('Page.navigate', { url }); await sleep(wait); },
    async until(expr, timeout = 60000, step = 250) {
      const end = Date.now() + timeout;
      while (Date.now() < end) { try { if (await evaluate(expr)) return true; } catch { } await sleep(step); }
      throw new Error('timed out: ' + expr.slice(0, 200));
    },
    async shot(path, clip) {
      const s = await send('Page.captureScreenshot', { format: 'png', ...(clip ? { clip: { ...clip, scale: 1 } } : {}) });
      fs.writeFileSync(path, Buffer.from(s.result.data, 'base64'));
    },
    mouse(type, x, y, extra = {}) {
      // On a move, `button` means a button is held: only drags send one.
      const dragging = type !== 'mouseMoved' || extra.buttons;
      return send('Input.dispatchMouseEvent', { type, x, y, button: dragging ? 'left' : 'none', buttons: type === 'mousePressed' ? 1 : 0, clickCount: 1, ...extra });
    },
    wheel(x, y, deltaY) { return send('Input.dispatchMouseEvent', { type: 'mouseWheel', x, y, deltaX: 0, deltaY }); },
    async key(key, code, vk, modifiers = 0) {
      await send('Input.dispatchKeyEvent', { type: 'keyDown', key, code, windowsVirtualKeyCode: vk, modifiers });
      await send('Input.dispatchKeyEvent', { type: 'keyUp', key, code, windowsVirtualKeyCode: vk, modifiers });
    },
    close() { ws.close(); chrome.kill(); },
  };
  return page;
}
