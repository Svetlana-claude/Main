// Сквозная проверка редактора на локальном запуске: показ, выбор деталей,
// сохранение, предпросмотр, экспорт, создание по фото и правка словами.
import { chromium } from 'playwright-core';
import { readdirSync, writeFileSync, readFileSync } from 'node:fs';
const kesh = process.env.HOME + '/.cache/ms-playwright/chromium-1234/';
const chrome = kesh + readdirSync(kesh).find((d) => d.startsWith('chrome-')) + '/chrome';
const ADRES = process.env.ADRES || 'http://127.0.0.1:8787/';
const b = await chromium.launch({ executablePath: chrome, args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
const s = await b.newPage({ viewport: { width: 1440, height: 900 }, acceptDownloads: true });
const oshibki = [];
s.on('pageerror', (e) => oshibki.push('pageerror: ' + e));
s.on('console', (m) => { if (m.type() === 'error') oshibki.push('console: ' + m.text()); });
s.on('dialog', (d) => d.accept());
const itog = [];
const ok = (uslovie, tekst) => { itog.push((uslovie ? 'OK   ' : 'FAIL ') + tekst); };

await s.goto(ADRES);
await s.waitForSelector('.dv-tabl tr[data-id]', { timeout: 20000 });
await s.waitForTimeout(1500);
await s.screenshot({ path: '/tmp/r1.png' });
ok(await s.locator('.dv-tabl tr[data-id]').count() === 10, 'таблица: 10 деталей');
ok(await s.locator('.dv-num').count() === 10, 'номера на модели: 10');

// Клик по строке таблицы → подсветка и форма детали.
await s.click('.dv-tabl tr[data-id="kupol"]');
ok(await s.locator('.dv-num.akt').textContent() === '2', 'клик по строке подсвечивает номер детали');
ok((await s.locator('#forma-chasti input').nth(1).inputValue()) === 'kupol', 'клик по строке открывает форму детали');
// Клик по номеру на модели → строка таблицы.
await s.click('.dv-num:text-is("9")');
ok(await s.locator('.dv-tabl tr.akt').getAttribute('data-id') === 'gruz', 'клик по детали подсвечивает строку');
// Клик в саму 3D-деталь (купол сверху по центру сцены).
await s.click('.dv-tabl tr[data-id="gruz"]');
const kupolXY = await s.evaluate(() => {
  const r = document.querySelector('.dv-scena canvas').getBoundingClientRect();
  const t = window.prosmotr.ekrannayaTochka('kupol');
  return { x: r.left + t.x, y: r.top + t.y };
});
await s.mouse.click(kupolXY.x, kupolXY.y);
ok(await s.locator('.dv-tabl tr.akt').getAttribute('data-id') === 'kupol', 'клик по куполу в 3D подсвечивает строку «Купол»');

// Правка: название детали меняется в таблице.
await s.click('.derevo li:has-text("Купол")');
await s.locator('#forma-chasti label:has-text("Название") input').fill('Купол основной');
await s.waitForTimeout(900);
ok(await s.locator('.dv-tabl tr[data-id="kupol"]').textContent().then((t) => t.includes('Купол основной')), 'правка названия попадает в таблицу');

// Взрыв и анимации.
await s.click('.dv button:text-is("Разобрать")');
await s.waitForTimeout(1600);
ok(await s.evaluate(() => +document.querySelector('.dv-ryad input[type=range]').value) > 0.99, 'кнопка «Разобрать» доводит ползунок до 1');
await s.click('.dv button:text-is("Раскачка")');
await s.click('.dv button:text-is("Снижение")');
await s.waitForTimeout(1200);
await s.screenshot({ path: '/tmp/r2.png' });
await s.click('.dv button:text-is("Собрать")');

// Сохранение на сервер.
await s.click('#b-sohranit');
await s.waitForTimeout(800);
ok(await s.locator('#spisok-modeley option[value="server:parashyut"]').count() === 1, 'сохранено в хранилище');

// Предпросмотр как на сайте.
await s.click('#b-predprosmotr');
const ramka = s.frameLocator('#ramka');
await ramka.locator('.dv-tabl tr[data-id]').first().waitFor({ timeout: 20000 });
await s.waitForTimeout(1500);
await s.screenshot({ path: '/tmp/r3.png' });
ok(await ramka.locator('.dv-tabl tr[data-id]').count() === 10, 'предпросмотр: таблица на месте');
ok(await ramka.locator('#b-sohranit, .vkladki, #b-sozdat').count() === 0, 'предпросмотр: элементов редактора нет');
await s.click('.razmery button[data-r="390x720"]');
await s.waitForTimeout(800);
await s.screenshot({ path: '/tmp/r4.png' });
await s.click('#b-zakryt');

// Экспорт.
const [zagr] = await Promise.all([s.waitForEvent('download'), s.click('#b-eksport')]);
await zagr.saveAs('/tmp/eksport-test.html');
const html = readFileSync('/tmp/eksport-test.html', 'utf8');
ok(!/\/api\/|redaktor\.js|sozdatPoFoto|ANTHROPIC|b-sozdat/.test(html), 'экспорт: нет редактора, серверных функций и ключей');
ok((html.match(/"id":"parashyut"/g) || []).length === 1 && !html.includes('"id":"samolet"'), 'экспорт: только одна модель');

// По фото (через заглушку ИИ).
await s.click('.vkladki button[data-v="foto"]');
await s.setInputFiles('#f-foto', ['/tmp/foto-test.png', '/tmp/foto-test.png']);
await s.waitForSelector('.foto img');
await s.locator('#foto-spisok select').nth(1).selectOption('сбоку');
await s.fill('#g-size', 'размах купола 8 м');
await s.fill('#g-name', 'Парашют по фото');
await s.click('#b-sozdat');
await s.waitForFunction(() => document.querySelector('.dv h1')?.textContent === 'Парашют по фото', null, { timeout: 30000 });
ok(true, 'создание по фото: модель открылась');
ok(await s.locator('#istochniki img').count() === 2, 'исходные фото сохранены и видны');
ok(await s.locator('#istochniki .podskazka').nth(1).textContent() === 'сбоку', 'вид фото сохранён');
await s.fill('#g-pravka', 'купол выше');
await s.click('#b-pravka');
await s.waitForFunction(() => document.querySelector('.dv h1')?.textContent === 'Парашют (поправлено)', null, { timeout: 30000 });
ok(true, 'правка словами применилась');
await s.waitForTimeout(800);
ok(/Запросов к ИИ сегодня: \d+ из 30/.test(await s.locator('#g-limity').textContent()), 'счётчик запросов к ИИ виден');

// Ключ ИИ не попадает в браузер.
const vse = await s.evaluate(() => document.documentElement.outerHTML + JSON.stringify(localStorage));
ok(!vse.includes('sk-test'), 'ключ ИИ не виден в браузере');
const log = readFileSync('/tmp/zaglushka-ii.log', 'utf8').trim().split('\n').map((l) => JSON.parse(l));
ok(log.length > 0 && log.every((z) => String(z.key).endsWith('sk-test-tolko-dlya-proverki')), 'ключ уходит к ИИ только с сервера');
ok(log.some((z) => z.url.startsWith('/v1/messages') && z.nachalo.includes('"file_id":"file_test_')), 'фото уходят к ИИ как файлы');

ok(oshibki.length === 0, 'ошибок в консоли нет' + (oshibki.length ? ':\n  ' + oshibki.join('\n  ') : ''));
console.log(itog.join('\n'));
await b.close();
