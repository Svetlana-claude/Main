// Проверка этапа без внешнего ИИ: кнопок нет, сервер отказывает, к ИИ ни одного
// запроса — даже при наличии ключа. Плюс хранение фото и экспортов.
import { chromium } from 'playwright-core';
import { readdirSync, existsSync, readFileSync, rmSync } from 'node:fs';
const kesh = process.env.HOME + '/.cache/ms-playwright/chromium-1234/';
const chrome = kesh + readdirSync(kesh).find((d) => d.startsWith('chrome-')) + '/chrome';
const ADRES = process.env.ADRES || 'http://127.0.0.1:8787/';
const KUKA = process.env.KUKA; // для проверки на сайте: пропуск временного входа
rmSync('/tmp/zaglushka-ii.log', { force: true });
const b = await chromium.launch({ executablePath: chrome, args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
const k = await b.newContext({ viewport: { width: 1440, height: 900 }, acceptDownloads: true });
if (KUKA) await k.addCookies([{ name: 'v2_session', value: KUKA, url: ADRES }]);
const s = await k.newPage();
const oshibki = [];
s.on('pageerror', (e) => oshibki.push(String(e)));
s.on('console', (m) => { if (m.type() === 'error' && !m.text().includes('400')) oshibki.push(m.text()); /* 400 — наши намеренные запросы */ });
s.on('dialog', (d) => d.accept());
const itog = [];
const ok = (u, t) => itog.push((u ? 'OK   ' : 'FAIL ') + t);
await s.goto(ADRES);
await s.waitForSelector('.dv-tabl tr[data-id]');
const st = await s.evaluate(() => fetch('api/status').then((r) => r.json()));
ok(st.ai === false, 'сервер сообщает: ИИ выключен');
await s.click('.vkladki button[data-v="foto"]');
ok(!(await s.locator('#b-sozdat').isVisible()) && !(await s.locator('#b-pravka').isVisible()), 'кнопок ИИ не видно');
for (const [put, telo] of [['generate', { id: 'proba', size: '1 м', photos: [{ n: 0 }] }], ['refine', { id: 'proba', instruction: 'выше', model: { name: 'x', parts: [{ id: 'a', name: 'a', shape: { type: 'group' } }] } }]]) {
  const o = await s.evaluate(async ([p, t]) => { const r = await fetch('api/' + p, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(t) }); return { c: r.status, t: await r.text() }; }, [put, telo]);
  ok(o.c === 400 && o.t.includes('выключено'), `прямой запрос ${put} отклонён`);
}
await s.click('#b-sohranit');
await s.waitForTimeout(600);
await s.setInputFiles('#f-foto', ['/tmp/foto-test.png', '/tmp/foto-test.png']);
await s.waitForSelector('#foto-spisok .foto img');
await s.locator('#foto-spisok select').nth(1).selectOption('сбоку');
await s.fill('#g-size', 'размах купола 8 м');
await s.click('#b-foto-sohranit');
await s.waitForFunction(() => document.querySelectorAll('#istochniki img').length === 2, null, { timeout: 15000 });
ok(await s.locator('#istochniki .podskazka').nth(1).textContent() === 'сбоку', 'фото сохранены к модели, вид на месте');
await s.waitForFunction(() => [...document.querySelectorAll('#istochniki img')].every((i) => i.complete && i.naturalWidth > 0));
ok(true, 'сохранённые фото открываются');
const [z] = await Promise.all([s.waitForEvent('download'), s.click('#b-eksport')]);
await z.path();
await s.waitForSelector('#eksporty a', { timeout: 8000 });
const [z2] = await Promise.all([s.waitForEvent('download'), s.click('#eksporty a')]);
await z2.saveAs('/tmp/iz-hranilishcha.html');
ok(readFileSync('/tmp/iz-hranilishcha.html', 'utf8').includes('id="dv-three"'), 'экспорт хранится и скачивается обратно');
await s.waitForTimeout(500);
ok(!existsSync('/tmp/zaglushka-ii.log'), 'к ИИ не ушло ни одного запроса');
ok(oshibki.length === 0, 'ошибок нет' + (oshibki.length ? ': ' + oshibki.join(' | ') : ''));
console.log(itog.join('\n'));
await b.close();
