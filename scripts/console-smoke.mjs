/**
 * Headless smoke test for the rebuilt chat console.
 *
 *   node scripts/console-smoke.mjs
 *
 * Serves web/ and stubs /api/* so the whole pipeline — route, recall, plan,
 * streamed draft, verify — runs offline. Asserts on the rendered DOM and fails
 * the process on any console error.
 */

import { chromium } from 'playwright';
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = fileURLToPath(new URL('../web/', import.meta.url));
const PORT = Number(process.env.PORT || 8571);
const OUT = fileURLToPath(new URL('../.console-shots/', import.meta.url));
fs.mkdirSync(OUT, { recursive: true });

const MIME = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml' };
const server = http.createServer((req, res) => {
  const p = path.join(ROOT, decodeURI(req.url.split('?')[0]));
  if (!p.startsWith(ROOT) || !fs.existsSync(p) || fs.statSync(p).isDirectory()) {
    res.writeHead(404); return res.end('not found');
  }
  res.writeHead(200, { 'content-type': MIME[path.extname(p)] || 'text/plain' });
  fs.createReadStream(p).pipe(res);
});
await new Promise(r => server.listen(PORT, r));

const ANSWER = `A 4090 node clears about **$41/month** at 40% utilisation once power is netted off — thin, but positive.

The drivers are payout rate, utilisation and electricity. At $0.89 per million tokens and roughly 950 tok/s sustained, a fully loaded node bills ~$2.19/day; at 40% that is $0.88. Power draw of 380W at $0.12/kWh costs $1.09/day at full load, $0.44 at 40%.

Break-even utilisation is **19.8%** — below that the electricity outruns the payout. See [[Unit Economics]] and [[Node Utilisation]].

\`\`\`mesh-chart
{"type":"bar","title":"Monthly margin by utilisation","subtitle":"RTX 4090, $0.12/kWh, estimate","x":"utilisation","y":["revenue","power","margin"],"unit":"usd",
 "data":[{"utilisation":"10%","revenue":6.6,"power":3.3,"margin":3.3},
         {"utilisation":"20%","revenue":13.1,"power":6.6,"margin":6.5},
         {"utilisation":"40%","revenue":26.3,"power":13.2,"margin":13.1},
         {"utilisation":"60%","revenue":39.4,"power":19.7,"margin":19.7},
         {"utilisation":"80%","revenue":52.6,"power":26.3,"margin":26.3}]}
\`\`\`

| Scenario | Utilisation | Margin |
| --- | --- | --- |
| Conservative | 20% | $6.50 |
| Base | 40% | $13.10 |
| Optimistic | 60% | $19.70 |
| Stretch | 80% | $26.30 |

The assumption most likely to be wrong is sustained throughput [1].`;

const AGENTS = [
  { id: 'c1', title: 'GPU node unit economics', status: 'idle', last_preview: 'Model the unit economics…', updated_at: new Date().toISOString(), unread_count: 0, pinned: false },
  { id: 'c2', title: 'Provider payout model', status: 'idle', last_preview: 'How are payouts computed…', updated_at: new Date(Date.now() - 2 * 864e5).toISOString(), unread_count: 0, pinned: false },
];

const browser = await chromium.launch({
  executablePath: process.env.CHROMIUM_PATH || '/opt/pw-browsers/chromium-1194/chrome-linux/chrome',
  args: ['--no-sandbox', '--disable-dev-shm-usage'],
});
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });

const errors = [];
let meshProbes = 0;
page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
page.on('requestfailed', r => errors.push('REQFAIL: ' + r.url()));
page.on('response', r => { if (r.status() >= 400) errors.push(`HTTP ${r.status()} ${r.url()}`); });
page.on('pageerror', e => errors.push('PAGEERROR: ' + e.message));

await page.addInitScript(() => {
  localStorage.setItem('nm_access_token', 'stub-token');
  localStorage.setItem('nm_email', 'walid@example.com');
  localStorage.removeItem('mesh.graph.v1');
});

const json = (body, status = 200) => ({ status, contentType: 'application/json', body: JSON.stringify(body) });

await page.route('**/api/**', async (route) => {
  const url = new URL(route.request().url());
  const p = url.pathname;
  const method = route.request().method();
  const body = (() => { try { return JSON.parse(route.request().postData() || '{}'); } catch { return {}; } })();

  if (p === '/api/agents' && method === 'GET')  return route.fulfill(json({ agents: AGENTS }));
  if (p === '/api/agents' && method === 'POST') {
    const row = { id: 'c' + (AGENTS.length + 1), title: null, status: 'idle', last_preview: null, updated_at: new Date().toISOString(), unread_count: 0, pinned: false };
    AGENTS.unshift(row); return route.fulfill(json(row));
  }
  if (p.endsWith('/messages')) return route.fulfill(json({ messages: [] }));

  if (p === '/api/agents/complete') {
    const r = {
      route:  { intent: 'analysis', needs_web: false, needs_memory: true, quantitative: true, language: 'en', complexity: 4 },
      plan:   { goal: 'Model node margin', steps: [{ q: 'Daily billing at full load?', needs: 'throughput x payout' }, { q: 'Power cost?', needs: 'draw x tariff' }, { q: 'Break-even?', needs: 'solve margin = 0' }], risks: ['Sustained throughput is assumed, not measured'] },
      verify: { ok: false, confidence: 0.72, issues: [{ severity: 'medium', kind: 'overclaim', quote: 'Break-even utilisation is 19.8%', fix: 'Label the break-even figure as an estimate; it depends on sustained throughput.' }] },
      title:  'GPU node unit economics',
    }[body.task] ?? '';
    return route.fulfill(json({ task: body.task, result: r, meta: { model: 'deepseek-ai/DeepSeek-V3.1', tokens: 120, latency_ms: 240 } }));
  }

  if (p === '/api/search') return route.fulfill(json({ results: [], provider: 'none' }));

  if (p === '/api/mesh/status') {
    meshProbes++;
    return route.fulfill(json({
      providers: [
        { node_id: 'node-lhr-03', status: 'online', latency_p50_ms: 180, latency_p95_ms: 390, success_rate: 0.995, tokens_today: 2100000, gpu: 'RTX 4090' },
        { node_id: 'node-fra-01', status: 'online', latency_p50_ms: 210, latency_p95_ms: 480, success_rate: 0.99,  tokens_today: 1240000, gpu: 'RTX 4090' },
        { node_id: 'node-sgp-02', status: 'online', latency_p50_ms: 340, latency_p95_ms: 720, success_rate: 0.97,  tokens_today: 880000,  gpu: 'A100' },
        { node_id: 'node-nyc-04', status: 'offline', latency_p50_ms: null, latency_p95_ms: null, success_rate: null, tokens_today: 0, gpu: null },
      ],
      online: 3, registered: 4, latency_p50_ms: 243, tokens_today: 4220000,
      fallback: { provider: 'siliconflow', model: 'deepseek-ai/DeepSeek-V3.1', active: false },
    }));
  }

  if (p.endsWith('/turn/stream')) {
    const frames = ANSWER.match(/[\s\S]{1,40}/g)
      .map(v => `data: ${JSON.stringify({ type: 'delta', v })}\n\n`).join('')
      + `data: ${JSON.stringify({ type: 'done', message_id: 'm1', created_at: new Date().toISOString(), meta: { model: 'deepseek-ai/DeepSeek-V3.1', served_by: 'api.siliconflow.com', tokens: 356, latency_ms: 2400, ttft_ms: 210 }, agent: { ...AGENTS[0], title: 'GPU node unit economics' } })}\n\n`
      + 'data: [DONE]\n\n';
    return route.fulfill({ status: 200, headers: { 'content-type': 'text/event-stream' }, body: frames });
  }

  if (p.endsWith('/turn')) {
    return route.fulfill(json({ assistant_message: { id: 'm1', role: 'assistant', content: ANSWER, created_at: new Date().toISOString() }, agent: AGENTS[0] }));
  }

  return route.fulfill(json({}, 404));
});

const shot = (n) => page.screenshot({ path: path.join(OUT, n + '.png') });

await page.goto(`http://localhost:${PORT}/chat.html`, { waitUntil: 'networkidle' });
await page.waitForTimeout(800);
await shot('01-welcome');

await page.click('[data-mode="analyze"]');
await page.fill('#input', 'Model the unit economics of an RTX 4090 node at 40% utilisation.');
await page.click('#sendBtn');
await page.waitForSelector('.prov:not([hidden])', { timeout: 20000 });
await page.waitForTimeout(700);
await shot('02-answer');

await page.click('[data-tab="graph"]'); await page.waitForTimeout(1400); await shot('03-graph');
await page.click('[data-tab="mesh"]');  await page.waitForTimeout(700);  await shot('04-mesh');
await page.click('[data-tab="vault"]'); await page.waitForTimeout(300);  await shot('05-vault');

await page.click('[data-tab="analysis"]'); await page.waitForTimeout(200);
const pin = page.locator('.figure [data-act="pin"]').first();
if (await pin.count()) { await pin.click(); await page.waitForTimeout(400); await shot('06-pinned'); }

await page.click('#themeBtn'); await page.waitForTimeout(400); await shot('07-light');
await page.click('#themeBtn'); await page.waitForTimeout(200);

// RTL: the beta rendered Arabic left-to-right with no direction handling.
await page.click('[data-mode="ask"]');
await page.fill('#input', 'حلل الأوضاع الاقتصادية و الفرص في السوق السعودي');
await page.click('#sendBtn');
await page.waitForTimeout(1200);
const userDir = await page.evaluate(() => {
  const els = document.querySelectorAll('.turn--user .usertext');
  return els.length ? els[els.length - 1].getAttribute('dir') : null;
});
await shot('08-rtl');

await page.setViewportSize({ width: 420, height: 860 });
await page.waitForTimeout(600);
await shot('09-mobile');
const mobileVisible = await page.evaluate(() => {
  const s = document.querySelector('.stream');
  const app = document.getElementById('app');
  return { w: s ? Math.round(s.getBoundingClientRect().width) : -1,
           h: s ? Math.round(s.getBoundingClientRect().height) : -1,
           cols: getComputedStyle(app).gridTemplateColumns,
           threads: app.dataset.threads, canvas: app.dataset.canvas };
});

const checks = await page.evaluate(() => ({
  turns:        document.querySelectorAll('.turn').length,
  figures:      document.querySelectorAll('.figure').length,
  charts:       document.querySelectorAll('svg.chart').length,
  provChips:    document.querySelectorAll('.prov .chip').length,
  wikilinks:    document.querySelectorAll('.wikilink').length,
  notes:        document.querySelectorAll('#graphNoteList .note').length,
  pipeSteps:    document.querySelectorAll('.pipe__step').length,
  selfCheck:    document.body.textContent.includes('Self-check flagged'),
  agentSidebar: /select an agent|agent list|message your agent/i.test(document.body.innerHTML),
}));

const fail = [];
if (checks.turns < 4)      fail.push('expected >= 4 turns');
if (checks.charts < 2)     fail.push('expected >= 2 rendered charts');
if (checks.provChips < 5)  fail.push('expected provenance chips');
if (checks.wikilinks < 2)  fail.push('expected [[wiki-links]] to render');
if (checks.pipeSteps < 5)  fail.push('expected a pipeline strip');
if (!checks.selfCheck)     fail.push('expected the self-check verdict to surface');
if (checks.agentSidebar)   fail.push('agent sidebar copy still present');
if (userDir !== 'rtl')     fail.push(`Arabic message dir was "${userDir}", expected "rtl"`);
if (!(mobileVisible.w > 200 && mobileVisible.h > 200)) fail.push('conversation not visible at 420px: ' + JSON.stringify(mobileVisible));
if (errors.length)         fail.push(`${errors.length} console error(s)`);
if (checks.figures < 4)    fail.push('expected the mesh pane to render its charts');

console.log('\nchecks:', JSON.stringify(checks, null, 2));
console.log('rtl dir:', userDir, '| mobile:', JSON.stringify(mobileVisible), '| mesh probes:', meshProbes);
if (errors.length) { console.log('\nconsole errors:'); errors.slice(0, 20).forEach(e => console.log('  • ' + e)); }
console.log(fail.length ? '\nFAIL\n  - ' + fail.join('\n  - ') : '\nPASS — screenshots in .console-shots/');

await browser.close();
server.close();
process.exit(fail.length ? 1 : 0);
