// «Модель по фото» и «Сверить с фото»: в сообщение уходят цифры сайта и сверка. Claude не запускается.
import { chromium } from 'playwright-core';
import { readdirSync } from 'node:fs';
const kesh = process.env.HOME + '/.cache/ms-playwright/chromium-1234/';
const chrome = kesh + readdirSync(kesh).find((d) => d.startsWith('chrome-')) + '/chrome';
const { ADRES, KUKA, FOTO } = process.env;
const b = await chromium.launch({ executablePath: chrome, args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
const k = await b.newContext({ viewport: { width: 1440, height: 900 } });
await k.addCookies([{ name: 'v2_session', value: KUKA, url: new URL(ADRES).origin }]);
const s = await k.newPage();
const oshibki = [];
s.on('pageerror', (e) => oshibki.push(String(e)));
const ushlo = [];
await s.route('**/chat/*/send', async (r) => {
  ushlo.push(new URLSearchParams(r.request().postData()).get('text'));
  await r.fulfill({ status: 200, contentType: 'application/json', body: '{"ok":true}' });
});
s.on('dialog', (d) => d.accept());
await s.goto(ADRES);
await s.waitForSelector('.dv-tabl tr[data-id]');
const [vybor] = await Promise.all([s.waitForEvent('filechooser'), s.click('#b-po-foto')]);
await vybor.setFiles(FOTO);
await s.waitForFunction(() => document.querySelector('#chat-tekst').value === '', null, { timeout: 60000 }).catch(() => {});
await s.waitForTimeout(1500);
const t1 = ushlo[0] || '';
console.log(/экономно/.test(t1) && /Цифры по фото/.test(t1) && /ширина к высоте|не отделился/.test(t1) ? 'OK   задача по фото с цифрами сайта' : 'FAIL задача: ' + t1.slice(0, 300));
await s.click('#b-sverka');
await s.waitForFunction(() => document.querySelector('#chat-tekst').value === '', null, { timeout: 60000 }).catch(() => {});
await s.waitForTimeout(1500);
const t2 = ushlo[1] || '';
console.log(/Сверка: слева фото/.test(t2) && /сверка — foto\//.test(t2) ? 'OK   сверка ушла одной картинкой' : 'FAIL сверка: ' + t2.slice(0, 300));
const put = (t2.match(/сверка — (foto\/[^\s;]+)/) || [])[1];
if (put) {
  const n = put.match(/\/(\d+)\.jpg$/)[1];
  const mid = put.split('/')[1];
  const r = await s.evaluate(async ([m, n]) => { const x = await fetch(`api/photos/${m}/${n}`); const bl = await x.blob(); const im = await createImageBitmap(bl); return [x.status, im.width, im.height]; }, [mid, n]);
  console.log(r[0] === 200 && r[1] > r[2] ? `OK   снимок сверки ${r[1]}×${r[2]}` : 'FAIL снимок сверки ' + r);
  await s.evaluate(async ([m, n]) => { const x = await fetch(`api/photos/${m}/${n}`); const bl = await x.blob(); const a = document.createElement('img'); a.id = 'pokaz'; a.src = URL.createObjectURL(bl); a.style = 'position:fixed;inset:0;z-index:99;max-width:100%;background:#fff'; document.body.append(a); }, [mid, n]);
  await s.waitForTimeout(800);
  await s.screenshot({ path: '/tmp/sverka.png' });
}
console.log(oshibki.length ? 'FAIL ошибки страницы: ' + oshibki.join(' | ') : 'OK   без ошибок страницы');
await b.close();
