// Run with Node 22+, an installed Playwright/Core package, and Chrome or Edge:
// PLAYWRIGHT_MODULE=/path/to/playwright-core node tests/android_ui_smoke.mjs
// --serve leaves the fixture server running for visual checks. No library calls.
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { readFile, mkdir, writeFile } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const pageHtml = await readFile(resolve(root, 'hdu_seat/web/index.html'), 'utf8');
const prefix = '/ui-test-secret/';
const fixture = () => ({
  cookie: 'synthetic-cookie-never-exposed-to-android-form', category_id: 591,
  content_id: 3, duration_hours: 4, num: 1, seat_ids: [], keywords: [],
  preferred_floor: null, avoid_near_door: false, poll_interval: 3,
  max_attempts: 200, email_enabled: false, smtp_host: '', smtp_port: 465,
  smtp_security: 'ssl', smtp_username: '', email_sender: '', email_recipient: '',
});
const seats = [
  { id: '1001', title: 'A-001', floor: 3, area: '三楼东区', available: true },
  { id: '1002', title: 'A-002', floor: 3, area: '三楼东区', available: true },
  { id: '1003', title: 'A-003', floor: 3, area: '三楼东区', available: false },
];
let saved, authenticated, status, rejectSave, calls, badPaths;
function reset() {
  saved = fixture(); authenticated = false; rejectSave = false; calls = []; badPaths = [];
  status = { running: false, waiting: false, history: [], seats: [], seat_revision: 0,
    notification: { status: 'disabled' } };
}
reset();
const server = createServer(async (req, res) => {
  const pathname = new URL(req.url, 'http://127.0.0.1').pathname;
  const json = (body, code = 200) => { res.writeHead(code, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(body)); };
  if (pathname === prefix || pathname === '/') {
    res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' }); res.end(pageHtml); return;
  }
  if (pathname === '/favicon.ico') { res.writeHead(204); res.end(); return; }
  if (pathname === '/__fixture__/ready') { json({ ready: true }); return; }
  const apiPrefix = pathname.startsWith(prefix) ? prefix : '/';
  const path = pathname.slice(apiPrefix.length);
  if (!path.startsWith('api/')) { badPaths.push(pathname); json({ error: 'Bad route' }, 404); return; }
  let body = '';
  for await (const chunk of req) body += chunk;
  body = body ? JSON.parse(body) : undefined;
  calls.push({ method: req.method, pathname, body });
  if (path === 'api/config') {
    if (req.method === 'POST') {
      if (rejectSave) { json({ error: '配置保存失败，请重试' }, 500); return; }
      saved = { ...saved, ...body, smtp_password_set: Boolean(body.smtp_password) || saved.smtp_password_set };
      if (body.smtp_password_clear) saved.smtp_password_set = false;
    }
    json(saved); return;
  }
  if (path === 'api/android/session') { json({ authenticated }); return; }
  if (path === 'api/status') { json(status); return; }
  if (path === 'api/seats') { json({ seats }); return; }
  if (path === 'api/run') {
    status.history.push({ at: '2026-10-20T12:00:00', status: 'dry-run', message: '试运行命中座位', seat: seats[0] });
    json({ status: 'dry-run' }); return;
  }
  if (path === 'api/start') {
    status.running = true; status.waiting = Boolean(body.schedule_at);
    status.scheduled_for = body.schedule_at; status.seats = seats; status.seat_revision++;
    json({ waiting: status.waiting, scheduled_for: body.schedule_at }); return;
  }
  if (path === 'api/stop') { status.running = false; status.waiting = false; json({}); return; }
  if (path === 'api/email/test') { json({ message: '测试邮件已提交，请检查收件箱。' }); return; }
  badPaths.push(pathname); json({ error: 'Unknown fixture route' }, 404);
});
await new Promise(resolveReady => server.listen(0, '127.0.0.1', resolveReady));
const origin = `http://127.0.0.1:${server.address().port}`;
if (process.argv.includes('--serve')) {
  authenticated = true;
  console.log(`${origin}${prefix}?platform=android`);
  await new Promise(() => {});
}

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright-core');
const executablePath = process.env.UI_BROWSER || [
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  '/usr/bin/chromium', '/usr/bin/google-chrome',
].find(existsSync);
const browser = await chromium.launch({ headless: true, ...(executablePath ? { executablePath } : {}) });
const results = [];
try {
  for (const width of [320, 390, 600]) {
    reset();
    const context = await browser.newContext({ viewport: { width, height: 844 }, isMobile: true, hasTouch: true });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.addInitScript(() => {
      window.nativeSignIns = 0; window.nativeSignOuts = 0;
      window.HduAndroid = {
        signIn: () => window.nativeSignIns++,
        signOut: () => window.nativeSignOuts++,
      };
    });
    await page.goto(`${origin}${prefix}?platform=android`);
    await page.locator('#accountState').filter({ hasText: '未登录' }).waitFor();
    assert.equal(await page.locator('#cookie').isVisible(), false, 'Android hides manual Cookie input');
    assert.equal(await page.locator('#cookie').inputValue(), '', 'Native credentials never enter the form');
    assert.equal(await page.locator('body').innerText().then(text => text.includes('Cookie')), false);
    await page.locator('button[onclick="querySeats()"]').first().click();
    await page.locator('#toast').filter({ hasText: '请先使用图书馆账号登录' }).waitFor();
    assert.equal(calls.some(call => call.pathname.endsWith('/api/seats')), false, 'Unauthenticated query is gated');
    await page.locator('#signInBtn').click();
    assert.equal(await page.evaluate(() => window.nativeSignIns), 1);
    authenticated = true;
    await page.evaluate(() => window.hduAndroidSessionChanged());
    await page.locator('#accountState').filter({ hasText: '已登录' }).waitFor();
    await page.locator('button[onclick="querySeats()"]').first().click();
    await page.locator('.seat-chip').first().waitFor();
    assert.equal(await page.locator('.seat-chip').count(), 3);
    await page.locator('.seat-chip').first().click();
    await page.locator('#toast').filter({ hasText: '目标座位已保存' }).waitFor();
    assert.deepEqual(saved.seat_ids, ['1001']);
    await page.reload();
    await page.waitForFunction(() => document.getElementById('seat_ids').value === '1001');
    await page.locator('#duration_hours').fill('6');
    rejectSave = true;
    await page.locator('.btn-save').click();
    await page.locator('#toast').filter({ hasText: '配置保存失败' }).waitFor();
    assert.equal(await page.locator('#duration_hours').inputValue(), '6', 'Save failure preserves entered settings');
    assert.equal(Number(saved.duration_hours), 4);
    rejectSave = false;
    await page.locator('.btn-save').click();
    await page.locator('#toast').filter({ hasText: '配置已保存' }).waitFor();
    assert.equal(Number(saved.duration_hours), 6);
    await page.locator('button[onclick="dryRun()"]').click();
    await page.locator('#toast').filter({ hasText: '命中座位' }).waitFor();
    await page.locator('#schedule_at').fill('2099-10-20T07:00');
    await page.locator('#schedule_at').blur();
    await page.keyboard.press('Escape');
    await page.locator('#startBtn').click();
    await page.locator('#runLabel').filter({ hasText: '等待至' }).waitFor();
    assert.equal(await page.locator('#stopBtn').isVisible(), true);
    assert.equal(await page.locator('#startBtn').isVisible(), false);
    await page.locator('#stopBtn').click();
    await page.locator('#runLabel').filter({ hasText: '空闲' }).waitFor();
    await page.locator('[data-section="email"]').click();
    await page.locator('#emailDetails summary').click();
    await page.locator('#smtp_host').fill('smtp.example.test');
    await page.locator('#smtp_username').fill('mail@example.test');
    await page.locator('#smtp_password').fill('synthetic-authorization-code');
    await page.locator('#email_recipient').fill('recipient@example.test');
    await page.locator('#testEmailBtn').click();
    await page.locator('#notificationMessage').filter({ hasText: '测试邮件已提交' }).waitFor();
    await page.locator('[data-section="logs"]').click();
    await page.waitForFunction(() => {
      const bounds = document.getElementById('logsPanel').getBoundingClientRect();
      return bounds.top < innerHeight && bounds.bottom > 70;
    });
    await page.locator('[data-section="settings"]').click();
    await page.locator('#signOutBtn').click();
    assert.equal(await page.evaluate(() => window.nativeSignOuts), 1);
    authenticated = false;
    await page.evaluate(() => window.hduAndroidSessionChanged());
    await page.locator('#accountState').filter({ hasText: '未登录' }).waitFor();
    assert.equal(await page.locator('#signOutBtn').isVisible(), false);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, 'No horizontal overflow');
    assert.equal(calls.filter(call => call.method === 'POST').every(call => !('cookie' in (call.body?.config || call.body || {}))), true, 'Android POST bodies omit Cookie');
    assert.equal(calls.every(call => call.pathname.startsWith(prefix)), true, 'All Android APIs retain secret URL prefix');
    assert.deepEqual(errors, []);
    assert.deepEqual(badPaths, []);
    results.push({ viewport: `${width}x844`, result: 'PASS', checks: 20 });
    await context.close();
  }
  reset();
  const desktop = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  await desktop.goto(origin);
  await desktop.waitForFunction(() => document.getElementById('cookie').value.length > 0);
  assert.equal(await desktop.locator('#cookie').isVisible(), true, 'Desktop Cookie workflow retained');
  assert.equal(await desktop.locator('.app-navigation').isVisible(), false);
  assert.equal(await desktop.locator('#signInBtn').isVisible(), false);
  assert.equal(await desktop.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  results.push({ viewport: '1280x900', result: 'PASS', checks: 4 });
  await mkdir(resolve(root, 'artifacts/android-ui'), { recursive: true });
  await writeFile(resolve(root, 'artifacts/android-ui/verification.json'), JSON.stringify(results, null, 2));
  console.log(JSON.stringify(results, null, 2));
} catch (error) {
  console.error(JSON.stringify({ status, recentCalls: calls.slice(-8) }, null, 2));
  throw error;
} finally {
  await browser.close();
  await new Promise(resolveClosed => server.close(resolveClosed));
}
