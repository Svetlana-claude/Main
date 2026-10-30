// Экспорт просмотрщика из командной строки — тем же кодом, что кнопка в редакторе.
//   node instrumenty/eksport.mjs public/modeli/parashyut.json ../prosmotrshchik/public/index.html
import { readFileSync, writeFileSync } from 'node:fs';
import { sobratStranicu } from '../public/dvizhok/eksport.js';
import { proverit } from '../public/dvizhok/format.js';

const [, , vhod, vyhod] = process.argv;
if (!vhod || !vyhod) {
  console.error('Нужно: путь к описанию модели и куда положить страницу.');
  process.exit(1);
}
const model = JSON.parse(readFileSync(vhod, 'utf8'));
const oshibki = proverit(model);
if (oshibki.length) {
  console.error('В описании ошибки:\n' + oshibki.join('\n'));
  process.exit(1);
}
const kornevaya = new URL('../public/', import.meta.url);
const chitat = (p) => readFileSync(new URL(p, kornevaya), 'utf8');
const html = sobratStranicu({
  model,
  three: chitat('vendor/three-bundle.min.js'),
  format: chitat('dvizhok/format.js'),
  dvizhok: chitat('dvizhok/dvizhok.js'),
});
writeFileSync(vyhod, html);
console.log(`Готово: ${vyhod} (${Math.round(html.length / 1024)} КБ)`);
