// Просмотрщик с сайта главпрыга — окном внутри другой страницы того же сайта.
import { chromium } from 'playwright-core';
import { readdirSync } from 'node:fs';
const kesh = process.env.HOME + '/.cache/ms-playwright/chromium-1234/';
const chrome = kesh + readdirSync(kesh).find((d) => d.startsWith('chrome-')) + '/chrome';
const b = await chromium.launch({ executablePath: chrome, args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
const s = await b.newPage();
await s.goto('https://mokeevasky.ru/glavpryg');
await s.evaluate(() => { const f = document.createElement('iframe'); f.id = 'vst'; f.src = '/glavpryg/model-3d/parashyutnaya-sistema/'; f.style = 'position:fixed;inset:0;width:100%;height:100%;z-index:99999;background:#fff'; document.body.append(f); });
const f = s.frameLocator('#vst');
await f.locator('.dv-tabl tr[data-id]').first().waitFor({ timeout: 30000 });
console.log(await f.locator('.dv-tabl tr[data-id]').count() === 10 ? 'OK   окном на странице главпрыга открывается' : 'FAIL вставка');
await b.close();
