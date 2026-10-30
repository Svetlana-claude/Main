import { chromium } from 'playwright-core';
import { readdirSync, readFileSync } from 'node:fs';
const kesh = process.env.HOME + '/.cache/ms-playwright/chromium-1234/';
const chrome = kesh + readdirSync(kesh).find((d) => d.startsWith('chrome-')) + '/chrome';
const b = await chromium.launch({ executablePath: chrome, args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
const s = await b.newPage();
await s.goto('http://127.0.0.1:8787/');
await s.waitForSelector('.dv-tabl tr[data-id]');
const html = await s.evaluate(async () => {
  const { sobratVBrauzere } = await import('/dvizhok/eksport.js');
  const m = await (await fetch('/modeli/parashyut.json')).json();
  return sobratVBrauzere(m);
});
const fayl = readFileSync('/home/mokeeva/main/3d/konstruktor/prosmotrshchik/public/index.html', 'utf8');
console.log(html === fayl ? 'OK   предпросмотр и выложенный просмотрщик — один и тот же файл' : 'FAIL различаются ' + html.length + ' ' + fayl.length);
await b.close();
