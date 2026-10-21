// Выгрузка варианта календаря в SVG со слоями — для дизайнера.
// Страница уже свёрстана браузером, поэтому берём готовые координаты: прямоугольники
// блоков, строки текста, встроенный SVG и картинки. Текст остаётся текстом
// (правится в редакторе, шрифты — отдельно), единицы — миллиметры.
// Запуск — vektor.py; здесь только функция window.VyvestiSvg(селектор варианта).

(() => {
const MM = 96 / 25.4;
const mm = v => +(v / MM).toFixed(3);
const NS_INK = 'http://www.inkscape.org/namespaces/inkscape';
let nomer = 0;
const preduprezhdeniya = new Set();
const shrifty = new Set();
const defs = [];

function Esc(s) { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }
const Prozrachnyy = c => !c || c === 'transparent' || /rgba\([^)]*,\s*0\)$/.test(c);

// --- псевдоэлементы → настоящие элементы, чтобы у них были координаты ---
function Soderzhimoe(content) {
  const chasti = content.match(/"((?:[^"\\]|\\.)*)"/g) || [];
  return chasti.map(c => c.slice(1, -1).replace(/\\a /gi, '\n').replace(/\\(.)/g, '$1')).join('');
}
function Materializovat(koren) {
  const spisok = [];
  koren.querySelectorAll('*').forEach(el => {
    if (el.closest('svg')) return;
    for (const ps of ['::before', '::after']) {
      const s = getComputedStyle(el, ps);
      if (s.content === 'none' || s.content === 'normal' || s.display === 'none') continue;
      spisok.push([el, ps, s]);
    }
  });
  const stil = [];
  for (const [el, ps, s] of spisok) {
    const span = document.createElement('span');
    span.className = `psevdo psevdo-${el.classList[0]}-${ps.slice(2)}`;
    let css = '';
    for (const k of s) if (k !== 'content') css += `${k}:${s.getPropertyValue(k)};`;
    span.style.cssText = css;
    span.textContent = Soderzhimoe(s.content);
    stil.push([el, ps, span]);
  }
  const st = document.createElement('style');
  st.textContent = '.bez-psevdo::before,.bez-psevdo::after{content:none!important}';
  document.head.append(st);
  for (const [el, ps, span] of stil) {
    el.classList.add('bez-psevdo');
    ps === '::before' ? el.prepend(span) : el.append(span);
  }
}

// --- фон и рамки блока ---
function Gradient(fn, x, y, w, h) {
  // linear-gradient(угол?, цвет поз?, ...) — только вертикальный и горизонтальный
  const m = fn.match(/^linear-gradient\((.*)\)$/s);
  if (!m) return null;
  const chasti = Razbit(m[1]);
  let ugol = 180;
  if (/deg$/.test(chasti[0])) ugol = parseFloat(chasti.shift());
  else if (/^to /.test(chasti[0])) ugol = { 'to bottom': 180, 'to top': 0, 'to right': 90, 'to left': 270 }[chasti.shift()] ?? 180;
  const id = `grad-${++nomer}`;
  const [x1, y1, x2, y2] = { 180: [0, 0, 0, 1], 0: [0, 1, 0, 0], 90: [0, 0, 1, 0], 270: [1, 0, 0, 0] }[ugol] || [0, 0, 0, 1];
  if (![0, 90, 180, 270].includes(ugol)) preduprezhdeniya.add(`градиент под углом ${ugol}° заменён вертикальным`);
  const stopy = chasti.map((c, i) => {
    const mm2 = c.match(/^(rgba?\([^)]*\)|#[0-9a-f]+|\w+)\s*([\d.]+%)?/i);
    return `<stop offset="${mm2[2] || (i / Math.max(chasti.length - 1, 1) * 100) + '%'}" stop-color="${mm2[1]}"/>`;
  }).join('');
  defs.push(`<linearGradient id="${id}" x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}">${stopy}</linearGradient>`);
  return `<rect x="${mm(x)}" y="${mm(y)}" width="${mm(w)}" height="${mm(h)}" fill="url(#${id})"/>`;
}
function Razbit(s) {
  // делит по запятым верхнего уровня
  const out = []; let gl = 0, tek = '';
  for (const ch of s) {
    if (ch === '(') gl++; if (ch === ')') gl--;
    if (ch === ',' && !gl) { out.push(tek.trim()); tek = ''; } else tek += ch;
  }
  if (tek.trim()) out.push(tek.trim());
  return out;
}
function Povtor(fn, x, y, w, h) {
  // repeating-linear-gradient(90deg, ...) — полосы прямоугольниками;
  // браузер отдаёт жёсткие переходы парами точек одного цвета: «цвет a, цвет b»
  const m = fn.match(/^repeating-linear-gradient\(90deg,(.*)\)$/s);
  if (!m) return null;
  const tochki = [];
  for (const c of Razbit(m[1])) {
    const t = c.match(/^(rgba?\([^)]*\)|#[0-9a-f]+|\w+)\s+(-?[\d.]+(?:px|mm))(?:\s+(-?[\d.]+(?:px|mm)))?$/i);
    if (!t) return null;
    const Px = v => parseFloat(v) * (/mm$/.test(v) ? MM : 1);
    tochki.push([t[1], Px(t[2])]);
    if (t[3] !== undefined) tochki.push([t[1], Px(t[3])]);
  }
  const period = tochki[tochki.length - 1][1] - tochki[0][1];
  if (period <= 0) return null;
  let out = '';
  for (let x0 = 0; x0 < w; x0 += period)
    for (let i = 0; i + 1 < tochki.length; i++) {
      const [c, a] = tochki[i], [c2, b] = tochki[i + 1];
      if (c !== c2 || Prozrachnyy(c) || b <= a) continue;
      const l = x0 + a, r = Math.min(x0 + b, w);
      if (r > l) out += `<rect x="${mm(x + l)}" y="${mm(y)}" width="${mm(r - l)}" height="${mm(h)}" fill="${c}"/>`;
    }
  return `<g>${out}</g>`;
}
async function Fon(el, s, r) {
  let out = '';
  const rad = parseFloat(s.borderTopLeftRadius) || 0;
  const krug = s.borderTopLeftRadius === '50%' || rad >= Math.min(r.width, r.height) / 2 - .01;
  const Forma = attr => krug && Math.abs(r.width - r.height) < .5
    ? `<circle cx="${mm(r.x + r.width / 2)}" cy="${mm(r.y + r.height / 2)}" r="${mm(r.width / 2)}" ${attr}/>`
    : `<rect x="${mm(r.x)}" y="${mm(r.y)}" width="${mm(r.width)}" height="${mm(r.height)}"${rad ? ` rx="${mm(rad)}"` : ''} ${attr}/>`;
  if (!Prozrachnyy(s.backgroundColor)) out += Forma(`fill="${s.backgroundColor}"`);
  if (s.backgroundImage !== 'none') {
    const sloi = Razbit(s.backgroundImage), razm = Razbit(s.backgroundSize), poz = Razbit(s.backgroundPosition);
    // нижний слой фона рисуется первым
    for (let i = sloi.length - 1; i >= 0; i--) {
      const fn = sloi[i];
      let [bw, bh] = (razm[i] || 'auto').split(' ');
      let [bx, by] = (poz[i] || '0px 0px').split(' ').map(v => /px$/.test(v) ? parseFloat(v) : v);
      const W = v => v === 'auto' || v === undefined ? r.width : /%$/.test(v) ? r.width * parseFloat(v) / 100 : parseFloat(v);
      const H = v => v === 'auto' || v === undefined ? r.height : /%$/.test(v) ? r.height * parseFloat(v) / 100 : parseFloat(v);
      if (fn.startsWith('url(')) { out += await FonKartinka(fn, s.backgroundSize, r); continue; }
      const w = bw === 'contain' || bw === 'cover' ? r.width : W(bw), h = bw === 'contain' || bw === 'cover' ? r.height : H(bh);
      const ox = typeof bx === 'number' ? bx : 0, oy = typeof by === 'number' ? by : 0;
      const g = Povtor(fn, r.x + ox, r.y + oy, w, h) || Gradient(fn, r.x + ox, r.y + oy, w, h);
      if (g) out += g; else preduprezhdeniya.add('пропущен фон: ' + fn.slice(0, 60));
    }
  }
  // рамки: одинаковые со скруглением — обводкой, иначе каждая сторона полосой
  const st = ['Top', 'Right', 'Bottom', 'Left'].map(k => [parseFloat(s[`border${k}Width`]) || 0, s[`border${k}Color`], s[`border${k}Style`]]);
  if (st.some(([w, c, t]) => w && t !== 'none' && !Prozrachnyy(c))) {
    const odinak = st.every(b => b[0] === st[0][0] && b[1] === st[0][1]);
    if (odinak && rad) out += `<rect x="${mm(r.x + st[0][0] / 2)}" y="${mm(r.y + st[0][0] / 2)}" width="${mm(r.width - st[0][0])}" height="${mm(r.height - st[0][0])}" rx="${mm(rad)}" fill="none" stroke="${st[0][1]}" stroke-width="${mm(st[0][0])}"/>`;
    else {
      const [t, p, b, l] = st;
      const Polosa = (x, y, w, h, c) => `<rect x="${mm(x)}" y="${mm(y)}" width="${mm(w)}" height="${mm(h)}" fill="${c}"/>`;
      if (t[0] && t[2] !== 'none' && !Prozrachnyy(t[1])) out += Polosa(r.x, r.y, r.width, t[0], t[1]);
      if (b[0] && b[2] !== 'none' && !Prozrachnyy(b[1])) out += Polosa(r.x, r.bottom - b[0], r.width, b[0], b[1]);
      if (l[0] && l[2] !== 'none' && !Prozrachnyy(l[1])) out += Polosa(r.x, r.y, l[0], r.height, l[1]);
      if (p[0] && p[2] !== 'none' && !Prozrachnyy(p[1])) out += Polosa(r.right - p[0], r.y, p[0], r.height, p[1]);
    }
  }
  return out;
}

// --- встроенный SVG: геометрия как есть, стили — вычисленные, явными атрибутами ---
const SVOYSTVA = ['fill', 'fill-opacity', 'fill-rule', 'stroke', 'stroke-width', 'stroke-opacity', 'stroke-linecap',
  'stroke-linejoin', 'stroke-dasharray', 'stroke-miterlimit', 'opacity', 'font-family', 'font-size', 'font-weight',
  'font-style', 'text-anchor', 'letter-spacing', 'stop-color', 'stop-opacity'];
const NASLED = ['fill', 'fill-opacity', 'fill-rule', 'stroke', 'stroke-width', 'stroke-opacity', 'stroke-linecap',
  'stroke-linejoin', 'font-family', 'font-size', 'font-weight', 'font-style', 'text-anchor', 'letter-spacing', 'color'];
const GEOMETRIYA = /^(d|x|y|x1|x2|y1|y2|cx|cy|r|rx|ry|width|height|points|transform|viewBox|offset|gradientUnits|gradientTransform|patternUnits|patternTransform|fx|fy|dx|dy|text-anchor|preserveAspectRatio|spreadMethod)$/;
const Chislo = v => v.replace(/^(-?[\d.]+)px$/, '$1');

function Ssylki(znach, pref) { return znach.replace(/url\(["']?(?:[^#"')]*)#([^"')]+)["']?\)/g, (_, id) => `url(#${pref}${id})`); }
function Atributy(el, pref, s) {
  let a = '';
  for (const at of el.attributes) {
    if (GEOMETRIYA.test(at.name)) a += ` ${at.name}="${Esc(at.value)}"`;
    if (at.name === 'id') a += ` id="${pref}${Esc(at.value)}"`;
  }
  const tekstovyy = /^(text|tspan|textPath)$/.test(el.localName);
  if (s) for (const k of SVOYSTVA) {
    if (!tekstovyy && /^(font-|text-anchor|letter-spacing)/.test(k)) continue;
    let v = s.getPropertyValue(k);
    if (!v || v === 'normal' && k === 'letter-spacing') continue;
    if (k === 'font-family') v = v.replace(/"/g, "'");
    a += ` ${k}="${Esc(Ssylki(Chislo(v), pref))}"`;
    if (k === 'font-family') shrifty.add(`${v}|${s.fontWeight}|${s.fontStyle}`);
  }
  return a;
}
function Peremennye(tekst, use, cvet) {
  // в содержимом <symbol> стили не вычисляются: подставляем var() и currentColor по <use>
  const cs = getComputedStyle(use);
  return tekst.replace(/var\((--[\w-]+)\s*(?:,\s*([^)]*))?\)/g, (_, k, zap) => cs.getPropertyValue(k).trim() || (zap || '').trim())
    .replace(/currentColor/g, cvet);
}
function Simvol(use, pref) {
  const id = (use.getAttribute('href') || use.getAttribute('xlink:href') || '').slice(1);
  const sym = document.getElementById(id);
  if (!sym) { preduprezhdeniya.add('нет символа #' + id); return ''; }
  const cs = getComputedStyle(use);
  const rodVb = use.ownerSVGElement.viewBox.baseVal;
  const w = parseFloat(use.getAttribute('width')) || rodVb.width, h = parseFloat(use.getAttribute('height')) || rodVb.height;
  const x = parseFloat(use.getAttribute('x')) || 0, y = parseFloat(use.getAttribute('y')) || 0;
  let tr = `translate(${x} ${y})`;
  const vb = sym.viewBox.baseVal;
  if (vb && vb.width) {
    const k = Math.min(w / vb.width, h / vb.height);
    tr += ` translate(${(w - vb.width * k) / 2} ${(h - vb.height * k) / 2}) scale(${k}) translate(${-vb.x} ${-vb.y})`;
  }
  let nasl = '';
  const estTekst = !!sym.querySelector('text');
  for (const k of NASLED) {
    if (k === 'color' || !estTekst && /^(font-|text-anchor|letter-spacing)/.test(k)) continue;
    let v = cs.getPropertyValue(k);
    if (k === 'font-family') { v = v.replace(/"/g, "'"); shrifty.add(`${v}|${cs.fontWeight}|${cs.fontStyle}`); }
    nasl += ` ${k}="${Esc(Chislo(v))}"`;
  }
  const vnutri = Peremennye(sym.innerHTML, use, cs.color).replace(/\sid="([^"]+)"/g, ` id="${pref}$1"`).replace(/url\(#([^)]+)\)/g, `url(#${pref}$1)`);
  return `<g transform="${tr}"${nasl}>${vnutri}</g>`;
}
function Uzly(el, pref) {
  let out = '';
  for (const n of el.childNodes) {
    if (n.nodeType === 3) { out += Esc(n.textContent); continue; }
    if (n.nodeType !== 1) continue;
    const tag = n.localName;
    if (['title', 'desc', 'style', 'script', 'symbol', 'metadata'].includes(tag)) continue;
    if (['defs', 'linearGradient', 'radialGradient', 'pattern', 'clipPath', 'mask', 'filter'].includes(tag)) {
      if (tag === 'defs') { out += Uzly(n, pref); continue; }
      defs.push(`<${tag}${Atributy(n, pref, null)}>${UzlyDefs(n, pref)}</${tag}>`);
      continue;
    }
    const s = getComputedStyle(n);
    if (s.display === 'none' || s.visibility === 'hidden') continue;
    if (tag === 'use') { out += Simvol(n, pref); continue; }
    if (tag === 'svg') { out += `<g transform="${SvgPreobr(n)}">${Uzly(n, pref)}</g>`; continue; }
    out += `<${tag}${Atributy(n, pref, s)}>${Uzly(n, pref)}</${tag}>`;
  }
  return out;
}
function UzlyDefs(el, pref) {
  // содержимое градиентов и фильтров переносим как есть
  return [...el.children].map(n => `<${n.localName}${[...n.attributes].map(a => ` ${a.name}="${a.name === 'id' ? pref + Esc(a.value) : Esc(Ssylki(a.value, pref))}"`).join('')}>${UzlyDefs(n, pref)}</${n.localName}>`).join('');
}
function SvgPreobr(n) {
  // вложенный svg: x, y, width, height + viewBox → преобразование
  const vb = n.viewBox.baseVal;
  const x = n.x.baseVal.value, y = n.y.baseVal.value, w = n.width.baseVal.value, h = n.height.baseVal.value;
  if (!vb || !vb.width) return `translate(${x} ${y})`;
  const k = Math.min(w / vb.width, h / vb.height);
  return `translate(${x + (w - vb.width * k) / 2} ${y + (h - vb.height * k) / 2}) scale(${k}) translate(${-vb.x} ${-vb.y})`;
}
function VstroennyySvg(el, r, pref) {
  const vb = el.viewBox.baseVal;
  let tr = `translate(${mm(r.x)} ${mm(r.y)})`;
  if (vb && vb.width) {
    const par = el.getAttribute('preserveAspectRatio') || '';
    let sx = r.width / vb.width, sy = r.height / vb.height, dx = 0, dy = 0;
    if (par !== 'none') { const k = Math.min(sx, sy); dx = (r.width - vb.width * k) / 2; dy = (r.height - vb.height * k) / 2; sx = sy = k; }
    tr = `translate(${mm(r.x + dx)} ${mm(r.y + dy)}) scale(${+(sx / MM).toFixed(6)} ${+(sy / MM).toFixed(6)}) translate(${-vb.x} ${-vb.y})`;
  } else tr += ` scale(${+(1 / MM).toFixed(6)})`;
  return `<g transform="${tr}">${Uzly(el, pref)}</g>`;
}

// --- картинки: SVG разворачиваем в вектор, растр встраиваем ---
async function Kartinka(img, r0, s) {
  // картинка рисуется в поле содержимого: без внутренних отступов и рамки
  const v = k => parseFloat(s[k]) || 0;
  const l = v('paddingLeft') + v('borderLeftWidth'), t = v('paddingTop') + v('borderTopWidth');
  const r = { x: r0.x + l, y: r0.y + t,
    width: r0.width - l - v('paddingRight') - v('borderRightWidth'),
    height: r0.height - t - v('paddingBottom') - v('borderBottomWidth') };
  const src = img.currentSrc || img.src;
  if (/\.svg(\?|$)/i.test(src)) {
    const tekst = await (await fetch(src)).text();
    const doc = new DOMParser().parseFromString(tekst, 'image/svg+xml').documentElement;
    const pref = `i${++nomer}-`;
    // временно на страницу: стили из <style> файла должны вычислиться
    const box = document.createElement('div');
    box.style.cssText = 'position:absolute;left:-9999px;top:0;width:100px;height:100px';
    const svg = document.importNode(doc, true);
    // классы файла (.cls-1 …) переименовываем, чтобы не задеть соседние файлы
    svg.querySelectorAll('style').forEach(st => st.textContent = st.textContent.replace(/\.([\w-]+)/g, `.${pref}$1`));
    svg.querySelectorAll('[class]').forEach(e => e.setAttribute('class', e.getAttribute('class').split(/\s+/).map(c => pref + c).join(' ')));
    svg.querySelectorAll('[id]').forEach(e => { e.setAttribute('id', pref + e.id); });
    svg.querySelectorAll('*').forEach(e => { for (const a of [...e.attributes]) if (/^(fill|stroke|clip-path|mask|filter|style)$/.test(a.name)) e.setAttribute(a.name, a.value.replace(/url\(#/g, `url(#${pref}`)); });
    svg.querySelectorAll('style').forEach(st => st.textContent = st.textContent.replace(/url\(#/g, `url(#${pref}`));
    box.append(svg); document.body.append(box);
    const out = VstroennyySvg(svg, r, '');
    box.remove();
    return out;
  }
  const blob = await (await fetch(src)).blob();
  const data = await new Promise(ok => { const fr = new FileReader(); fr.onload = () => ok(fr.result); fr.readAsDataURL(blob); });
  const par = { fill: 'none', contain: 'xMidYMid meet', cover: 'xMidYMid slice' }[s.objectFit] || 'none';
  const imya = src.split('/').pop();
  preduprezhdeniya.add(`растр встроен: ${imya} (${img.naturalWidth}×${img.naturalHeight})`);
  return `<image x="${mm(r.x)}" y="${mm(r.y)}" width="${mm(r.width)}" height="${mm(r.height)}" preserveAspectRatio="${par}" xlink:href="${data}"><title>${Esc(imya)}</title></image>`;
}
async function FonKartinka(fn, size, r) {
  const url = fn.match(/^url\("?(.*?)"?\)$/s)[1];
  if (!url.startsWith('data:image/svg+xml')) { preduprezhdeniya.add('пропущена фоновая картинка ' + url.slice(0, 40)); return ''; }
  const tekst = decodeURIComponent(url.replace(/^data:image\/svg\+xml(;utf8)?,/, ''));
  const svg = new DOMParser().parseFromString(tekst, 'image/svg+xml').documentElement;
  const box = document.createElement('div'); box.style.cssText = 'position:absolute;left:-9999px;top:0';
  const el = document.importNode(svg, true); box.append(el); document.body.append(box);
  const out = VstroennyySvg(el, r, `b${++nomer}-`);  // contain по центру — как в макете
  box.remove();
  return out;
}

// --- текст: строка за строкой, с координатами браузера ---
const holst = document.createElement('canvas').getContext('2d');
function Tekst(uzel, s, o, prozr) {
  const t = uzel.textContent;
  if (!t.trim()) return '';
  const rng = document.createRange(), stroki = [];
  for (let i = 0; i < t.length; i++) {
    rng.setStart(uzel, i); rng.setEnd(uzel, i + 1);
    const q = rng.getClientRects()[0];
    if (!q || (!q.width && /\s/.test(t[i]))) continue;
    let st = stroki.find(x => Math.abs(x.top - q.top) < q.height / 2);
    if (!st) stroki.push(st = { top: q.top, left: q.left, tekst: '' });
    st.tekst += t[i];
  }
  holst.font = `${s.fontStyle} ${s.fontWeight} ${s.fontSize} ${s.fontFamily}`;
  const m = holst.measureText('Hg');
  const sem = s.fontFamily.replace(/"/g, "'");
  shrifty.add(`${s.fontFamily}|${s.fontWeight}|${s.fontStyle}`);
  const reg = { uppercase: x => x.toUpperCase(), lowercase: x => x.toLowerCase() }[s.textTransform] || (x => x);
  const ls = s.letterSpacing === 'normal' ? '' : ` letter-spacing="${mm(parseFloat(s.letterSpacing))}px"`;
  // оптический размер переменного шрифта (Inter: ось opsz) браузер берёт по кеглю в точках;
  // в SVG кегль в миллиметрах — без явной оси буквы шире, чем в макете
  const osi = s.fontOpticalSizing === 'auto' && s.fontVariationSettings === 'normal'
    ? ` style="font-variation-settings:'opsz' ${parseFloat(s.fontSize).toFixed(1)}"` : '';
  return stroki.map(st => {
    const tx = reg(st.tekst.replace(/\s+$/, ''));
    return `<text x="${mm(st.left - o.x)}" y="${mm(st.top - o.y + m.fontBoundingBoxAscent)}" font-family="${Esc(sem)}" font-size="${mm(parseFloat(s.fontSize))}" font-weight="${s.fontWeight}"${osi}${s.fontStyle !== 'normal' ? ` font-style="${s.fontStyle}"` : ''}${ls} fill="${s.color}"${prozr < 1 ? ` opacity="${prozr}"` : ''} xml:space="preserve">${Esc(tx)}</text>`;
  }).join('');
}

// --- обход листа ---
const NAZV = {
  fon: 'Метки сетки', konstr: 'Сетка (скрыта)', god: 'Год', zag: 'Заголовок', meta: 'Подпись', tekst: 'Заголовок',
  'molekula-j': 'Молекула', 'molekula-k': 'Молекула', kartochki: 'Состав', 'sostav-k': 'Состав', geroinya: 'Героиня',
  logo: 'Логотип', 'logo-mal': 'Логотип', lineyka: 'Линейки', metka: 'Подписи линеек', pruzhina: 'Пружина',
  'mes-zag': 'Номер и название месяца', 'shapka-mes': 'Номер и название месяца', 'psevdo-mes-after': 'Справка о веществе',
  prim: 'Подпись о выходных', daty: 'Важные даты', tovary: 'Товары', kontakty: 'Контакты', qr: 'QR-код', 'mol-polosa': 'Молекула',
};
function Sloy(el, list) {
  if (el === list) return 'Фон';
  if (el.closest('.konstr')) return 'Сетка (скрыта)';
  if (el.closest('.dni')) {
    if (el.closest('.dni') === el) return 'Фон месяца';
    if (el.classList.contains('psevdo') && el.closest('.prazd, .rab')) return 'Праздники';
    return el.closest('.dn') ? 'Дни недели' : 'Числа';
  }
  if (el.closest('.daty')) return 'Важные даты';
  let x = el;
  while (x.parentElement && x.parentElement !== list && !x.parentElement.classList.contains('mes')) x = x.parentElement;
  if (el.classList.contains('mes')) return 'Фон месяца';
  const kl = [...x.classList].find(c => NAZV[c]) || x.classList[0] || x.localName;
  return NAZV[kl] || kl;
}
async function Obhod(el, list, o, sloi, prozr) {
  const s = getComputedStyle(el);
  if (s.display === 'none') return;
  prozr *= parseFloat(s.opacity);
  if (s.transform !== 'none') preduprezhdeniya.add(`преобразование ${s.transform} у .${el.classList[0]} не перенесено`);
  if (s.filter !== 'none') preduprezhdeniya.add(`фильтр у .${el.classList[0]} не перенесён`);
  const imya = Sloy(el, list);
  const sloy = sloi.get(imya) || (sloi.set(imya, []), sloi.get(imya));
  const b = el.getBoundingClientRect();
  const r = new DOMRect(b.x - o.x, b.y - o.y, b.width, b.height);
  const Dobavit = svg => { if (svg) sloy.push(prozr < 1 ? `<g opacity="${prozr}">${svg}</g>` : svg); };
  if (s.visibility !== 'hidden') {
    // подложка и рамка — и у картинок: белое поле под QR задано фоном самого <img>
    Dobavit(await Fon(el, s, r));
    if (el.localName === 'svg') { Dobavit(VstroennyySvg(el, r, `s${++nomer}-`)); return; }
    if (el.localName === 'img') { Dobavit(await Kartinka(el, r, s)); return; }
  }
  for (const n of el.childNodes) {
    if (n.nodeType === 3 && s.visibility !== 'hidden') Dobavit(Tekst(n, s, o, 1));
    else if (n.nodeType === 1) await Obhod(n, list, o, sloi, prozr);
  }
}
function Mesyac(list) {
  const m = list.querySelector('.mes');
  if (!m) return null;
  const nazv = ['', 'Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь', 'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь'];
  return `${nazv[+m.dataset.m]} ${m.dataset.y}`;
}
function Sloi(sloi) {
  return [...sloi].filter(([, v]) => v.length).map(([k, v]) =>
    `<g inkscape:groupmode="layer" inkscape:label="${Esc(k)}" id="sloy-${++nomer}"${k.includes('скрыта') ? ' style="display:none"' : ''}>\n${v.join('\n')}\n</g>`).join('\n');
}

window.VyvestiSvg = async sel => {
  const vr = document.querySelector(sel);
  Materializovat(vr);
  const trio = vr.querySelector('.trio');
  const o0 = trio.getBoundingClientRect();
  const listy = [];
  for (const list of trio.children) {
    const r = list.getBoundingClientRect();
    const sloi = new Map([['Фон', []]]);
    await Obhod(list, list, r, sloi, 1);
    const imya = list.classList.contains('shapka') ? 'Шапка' : list.classList.contains('polosa') ? 'Рекламная полоса' : `Блок — ${Mesyac(list)}`;
    listy.push({ imya, x: r.x - o0.x, y: r.y - o0.y, w: r.width, h: r.height, soderzhimoe: Sloi(sloi) });
  }
  const Shapka = (w, h) => `<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" xmlns:inkscape="${NS_INK}" xmlns:sodipodi="http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd" width="${mm(w)}mm" height="${mm(h)}mm" viewBox="0 0 ${mm(w)} ${mm(h)}">
<sodipodi:namedview inkscape:document-units="mm"/>`;
  const Defs = () => `<defs>\n${defs.join('\n')}\n${listy.map((l, i) => `<clipPath id="obrez-${i}"><rect width="${mm(l.w)}" height="${mm(l.h)}"/></clipPath>`).join('\n')}\n</defs>`;
  // обрез по листу — на самом слое, иначе вложенные слои перестают быть слоями
  const List = (l, i, dx, dy) => `<g inkscape:groupmode="layer" inkscape:label="${Esc(l.imya)}" id="list-${i}" transform="translate(${mm(dx)} ${mm(dy)})" clip-path="url(#obrez-${i})">\n${l.soderzhimoe}\n</g>`;
  const polnyy = `${Shapka(o0.width, o0.height)}\n${Defs()}\n${listy.map((l, i) => List(l, i, l.x, l.y)).join('\n')}\n</svg>\n`;
  const otdelno = listy.map((l, i) => ({ imya: l.imya, svg: `${Shapka(l.w, l.h)}\n${Defs()}\n${List(l, i, 0, 0)}\n</svg>\n` }));
  return { polnyy, otdelno, shrifty: [...shrifty], preduprezhdeniya: [...preduprezhdeniya] };
};
})();
