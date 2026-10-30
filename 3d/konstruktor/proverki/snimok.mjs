// Снимки стенда: node snimok.mjs <модель> <файл> [действия JSON]
import { chromium } from 'playwright-core';
import { readdirSync } from 'node:fs';
const kesh = process.env.HOME + '/.cache/ms-playwright/chromium-1234/';
const chrome = kesh + readdirSync(kesh).find((d) => d.startsWith('chrome-')) + '/chrome';
const [, , model = 'parashyut', fayl = '/tmp/snimok.png', deystviya = '[]'] = process.argv;
const brauzer = await chromium.launch({ executablePath: chrome, args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
const str = await brauzer.newPage({ viewport: { width: 1280, height: 800 } });
const oshibki = [];
str.on('pageerror', (e) => oshibki.push(String(e)));
str.on('console', (m) => { if (m.type() === 'error' || m.type() === 'warning') oshibki.push(m.text()); });
await str.goto(`http://127.0.0.1:8765/proverki/stend.html?m=${model}`);
await str.waitForFunction(() => window.gotovo || document.body.textContent.includes('Ошиб'), null, { timeout: 20000 }).catch(() => {});
for (const d of JSON.parse(deystviya)) {
  if (d.zhdat) await str.waitForTimeout(d.zhdat);
  if (d.js) await str.evaluate(d.js);
  if (d.klik) await str.click(d.klik);
}
await str.waitForTimeout(1500);
await str.screenshot({ path: fayl });
console.log(oshibki.length ? 'ОШИБКИ:\n' + oshibki.join('\n') : 'без ошибок');
await brauzer.close();
