// Редактор: список моделей, правка деталей и анимаций, создание по фото,
// предпросмотр и экспорт. Показ модели — тот же движок, что и в просмотрщике.

import { sozdatProsmotr } from './dvizhok/dvizhok.js';
import { proverit, FORMY, ANIMACII } from './dvizhok/format.js';
import { sobratVBrauzere } from './dvizhok/eksport.js';
import { sozdatChat } from './chat3d.js';

const $ = (s) => document.querySelector(s);
const el = (teg, attrs = {}, ...deti) => {
  const e = document.createElement(teg);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') e.className = v;
    else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
    else if (v !== undefined && v !== null && v !== false) e.setAttribute(k, v === true ? '' : v);
  }
  for (const d of deti.flat()) if (d != null) e.append(d);
  return e;
};

// ---------- Состояние ----------
let model = null;          // текущее описание
let istochnik = null;      // откуда открыто: { gde: 'server' | 'vstroennaya' | 'brauzer', id }
let prosmotr = null;       // движок
let vybrannaya = null;     // id выбранной части
let server = null;         // ответ /api/status или null, если сервера нет
let fotoNaZagruzku = [];   // [{ vid, data, type, prevyu }]
let izmeneno = false;
let zapisModeli = null;     // запись из хранилища: модель и её материалы
let versiya = 0;           // какую версию файла модели показываем
let chatOkno = null;       // окно разговора: только на нашем сервере

const VIDY = ['спереди', 'сзади', 'слева', 'справа', 'сверху', 'снизу', 'сбоку', 'три четверти', 'деталь крупно'];
const LOKALNYE = 'konstruktor3d:modeli';

// ---------- Сообщения ----------
let tajmerStatusa = null;
function soobshchit(tekst, oshibka = false, dolgo = false) {
  const s = $('#status');
  s.textContent = tekst;
  s.classList.toggle('oshibka', oshibka);
  s.classList.add('vidno');
  clearTimeout(tajmerStatusa);
  tajmerStatusa = setTimeout(() => s.classList.remove('vidno'), dolgo || oshibka ? 9000 : 3000);
}

// ---------- Сервер ----------
async function api(put, opts = {}) {
  const r = await fetch('api/' + put, {
    ...opts,
    headers: opts.body ? { 'content-type': 'application/json' } : undefined,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  let dannye = null;
  try { dannye = await r.json(); } catch { /* пусто */ }
  if (r.status === 403 && !dannye) throw new Error('Вход истёк — обновите страницу и войдите снова.');
  if (!r.ok || (dannye && dannye.error)) throw new Error((dannye && dannye.error) || `Сервер ответил ошибкой ${r.status}`);
  return dannye;
}

async function uznatServer() {
  try {
    server = await api('status');
  } catch {
    server = null;
  }
  $('#kto').textContent = server?.email ? `Вход: ${server.email}` : server ? '' : 'Без сервера: сохранение только в этом браузере';
  obnovitLimity();
}

function obnovitLimity() {
  const l = $('#g-limity');
  $('#blok-ii').hidden = !server?.ai;
  if (!server) l.textContent = 'Серверная часть не запущена: фото и экспорты здесь не хранятся.';
  else if (server.ai) l.textContent = `Запросов к ИИ сегодня: ${server.used} из ${server.limit}. За раз — до ${server.maxPhotos} фото.`;
  else l.textContent = '';
}

// ---------- Список моделей ----------
const lokalnye = () => JSON.parse(localStorage.getItem(LOKALNYE) || '{}');

async function zagruzitSpisok(vybrat) {
  const sel = $('#spisok-modeley');
  sel.innerHTML = '';
  const gruppa = (nazv) => { const g = el('optgroup', { label: nazv }); sel.append(g); return g; };
  if (server) {
    try {
      const { models } = await api('models');
      if (models.length) {
        const g = gruppa('Сохранённые');
        for (const m of models) g.append(el('option', { value: 'server:' + m.id }, m.name || m.id));
      }
    } catch (e) { soobshchit('Список моделей не загрузился: ' + e.message, true); }
  } else {
    const l = lokalnye();
    if (Object.keys(l).length) {
      const g = gruppa('В этом браузере');
      for (const [id, m] of Object.entries(l)) g.append(el('option', { value: 'brauzer:' + id }, m.name || id));
    }
  }
  // С чатом образцы лежат среди сохранённых: Claude правит те же файлы.
  if (!server?.chat) {
    const vstr = await (await fetch('modeli/spisok.json')).json();
    const g = gruppa('Образцы');
    for (const m of vstr) g.append(el('option', { value: 'vstroennaya:' + m.id }, m.name));
  }
  if (vybrat) sel.value = vybrat;
}

async function otkryt(klyuch) {
  if (izmeneno && !confirm('Есть несохранённые изменения. Открыть другую модель?')) {
    $('#spisok-modeley').value = istochnik ? `${istochnik.gde}:${istochnik.id}` : '';
    return;
  }
  const [gde, id] = klyuch.split(/:(.*)/s);
  let m;
  let zapis = null;
  if (gde === 'server') { zapis = await api('models/' + encodeURIComponent(id)); m = zapis.model; versiya = zapis.version; }
  else if (gde === 'brauzer') m = lokalnye()[id];
  else m = await (await fetch(`modeli/${id}.json`)).json();
  istochnik = { gde, id };
  ustanovitModel(m, { sbrosKamery: true });
  pokazatIstochniki(zapis);
  izmeneno = false;
  chatOkno?.pokazat(gde === 'server' ? id : null);
}

// ---------- Модель и показ ----------
function ustanovitModel(m, { sbrosKamery = false } = {}) {
  model = m;
  $('#m-name').value = model.name || '';
  $('#m-scale').value = model.scale?.text || '';
  $('#g-name').value = model.name || '';
  $('#g-size').value = model.scale?.text || '';
  perestroit(sbrosKamery);
  narisovatDerevo();
  narisovatAnimacii();
  $('#json').value = JSON.stringify(model, null, 2);
}

function perestroit(sbrosKamery = false) {
  const oshibki = proverit(model);
  if (oshibki.length) {
    soobshchit('В описании ошибки:\n' + oshibki.slice(0, 6).join('\n'), true);
    return false;
  }
  const kamera = !sbrosKamery && prosmotr ? prosmotr.kameraSostoyanie() : null;
  prosmotr?.unichtozhit();
  try {
    prosmotr = sozdatProsmotr($('#scena'), model, { snimki: true, kamera });
    window.prosmotr = prosmotr;
  } catch (e) {
    soobshchit('Модель не построилась: ' + e.message, true);
    return false;
  }
  prosmotr.naVybor((id, otkuda) => {
    vybrannaya = id;
    if (otkuda !== 'redaktor') { narisovatDerevo(); narisovatFormu(); }
  });
  if (vybrannaya) prosmotr.vybrat(vybrannaya, 'redaktor');
  return true;
}

let tajmerPerestroyki = null;
function izmenit(bezDereva = false) {
  izmeneno = true;
  clearTimeout(tajmerPerestroyki);
  tajmerPerestroyki = setTimeout(() => {
    perestroit();
    if (!bezDereva) narisovatDerevo();
    $('#json').value = JSON.stringify(model, null, 2);
  }, 350);
}

// ---------- Дерево частей ----------
function poryadokChastey() {
  const deti = new Map();
  for (const p of model.parts) {
    const k = p.parent ?? null;
    if (!deti.has(k)) deti.set(k, []);
    deti.get(k).push(p);
  }
  const itog = [];
  const obhod = (rod, glub) => (deti.get(rod) || []).forEach((p) => { itog.push([p, glub]); obhod(p.id, glub + 1); });
  obhod(null, 0);
  return itog;
}

function narisovatDerevo() {
  const ul = $('#derevo');
  ul.innerHTML = '';
  for (const [p, glub] of poryadokChastey()) {
    const li = el('li', { class: p.id === vybrannaya ? 'akt' : '', style: `padding-left:${8 + glub * 14}px` },
      el('span', { class: 'n' }, p.num != null ? String(p.num) : '·'),
      el('span', {}, p.name || p.id),
      el('span', { class: 'id' }, p.id));
    li.onclick = () => { vybrannaya = p.id; prosmotr?.vybrat(p.num != null ? p.id : null, 'redaktor'); narisovatDerevo(); narisovatFormu(); };
    ul.append(li);
  }
  narisovatFormu();
}

const chisla = (znach, naIzm) => el('div', { class: 'tri' },
  [0, 1, 2].map((i) => el('input', {
    type: 'number', step: '0.01', value: znach?.[i] ?? 0,
    oninput: (e) => { const v = [...(znach || [0, 0, 0])]; v[i] = +e.target.value || 0; znach = v; naIzm(v); },
  })));

function pereimenovat(staryy, novyy) {
  for (const p of model.parts) {
    if (p.id === staryy) p.id = novyy;
    if (p.parent === staryy) p.parent = novyy;
    if (p.shape?.type === 'lines') {
      for (const k of ['from', 'to']) {
        const zam = (s) => (typeof s === 'string' && s.split(':')[0] === staryy ? novyy + s.slice(staryy.length) : s);
        p.shape[k] = Array.isArray(p.shape[k]) ? p.shape[k].map(zam) : zam(p.shape[k]);
      }
    }
  }
  for (const a of model.animations || []) {
    if (a.target === staryy) a.target = novyy;
    for (const t of a.params?.pulls || []) if (t.part === staryy) t.part = novyy;
    if (a.params?.flap?.part === staryy) a.params.flap.part = novyy;
  }
}

function narisovatFormu() {
  const f = $('#forma-chasti');
  f.innerHTML = '';
  const p = model.parts.find((x) => x.id === vybrannaya);
  if (!p) { f.append(el('p', { class: 'podskazka' }, 'Выберите деталь в списке или щёлкните по ней на модели.')); return; }
  const pole = (nazv, input) => el('label', {}, nazv, input);
  const roditeli = el('select', { onchange: (e) => { p.parent = e.target.value || null; izmenit(); } },
    el('option', { value: '' }, '— корень —'),
    model.parts.filter((x) => x.id !== p.id).map((x) => el('option', { value: x.id, selected: x.id === p.parent }, `${x.name} (${x.id})`)));
  const formaTekst = el('textarea', { class: 'kod', spellcheck: 'false' });
  formaTekst.value = JSON.stringify(p.shape || { type: 'group' }, null, 1);
  formaTekst.oninput = () => {
    try { p.shape = JSON.parse(formaTekst.value); formaTekst.style.borderColor = ''; izmenit(true); }
    catch { formaTekst.style.borderColor = '#c0392b'; }
  };
  const vz = p.explode || { dir: [0, 1, 0], dist: 0 };
  f.append(
    el('div', { class: 'dva' },
      pole('Номер', el('input', { type: 'number', min: 1, value: p.num ?? '', oninput: (e) => { p.num = e.target.value === '' ? undefined : Math.round(+e.target.value); izmenit(); } })),
      pole('id', el('input', { value: p.id, onchange: (e) => {
        const nov = e.target.value.trim();
        if (!nov || model.parts.some((x) => x.id === nov)) { e.target.value = p.id; soobshchit('Такой id пустой или уже занят.', true); return; }
        pereimenovat(p.id, nov); vybrannaya = nov; izmenit();
      } }))),
    pole('Название', el('input', { value: p.name || '', oninput: (e) => { p.name = e.target.value; izmenit(); } })),
    pole('Описание (пара предложений)', (() => { const t = el('textarea'); t.value = p.desc || ''; t.oninput = () => { p.desc = t.value; izmenit(true); }; return t; })()),
    el('div', { class: 'dva' },
      pole('Родитель', roditeli),
      pole('Цвет', el('input', { type: 'color', value: /^#[0-9a-f]{6}$/i.test(p.color || '') ? p.color : '#9aa7b4', oninput: (e) => { p.color = e.target.value; izmenit(true); } }))),
    pole('Положение, м (x, y, z)', chisla(p.position, (v) => { p.position = v; izmenit(true); })),
    pole('Поворот, градусы', chisla(p.rotation, (v) => { p.rotation = v; izmenit(true); })),
    pole('Взрыв: направление', chisla(vz.dir, (v) => { p.explode = { ...vz, dir: v }; Object.assign(vz, p.explode); izmenit(true); })),
    pole('Взрыв: расстояние, м', el('input', { type: 'number', step: '0.1', value: vz.dist ?? 0, oninput: (e) => { p.explode = { ...vz, dist: +e.target.value || 0 }; Object.assign(vz, p.explode); izmenit(true); } })),
    pole('Форма и её размеры', formaTekst),
    el('p', { class: 'podskazka' }, 'Формы: ' + Object.entries(FORMY).map(([k, v]) => `${k} — ${v}`).join('; ')),
    el('div', { class: 'knopki' },
      el('button', { onclick: () => {
        const kopiya = structuredClone(p);
        kopiya.id = unikalnyId(p.id);
        if (kopiya.num != null) kopiya.num = svobodnyNomer();
        model.parts.push(kopiya); vybrannaya = kopiya.id; izmenit();
      } }, 'Копия'),
      el('button', { onclick: () => udalitChast(p) }, 'Удалить')),
  );
}

const unikalnyId = (baza) => { let i = 2; while (model.parts.some((x) => x.id === `${baza}-${i}`)) i++; return `${baza}-${i}`; };
const svobodnyNomer = () => Math.max(0, ...model.parts.map((x) => x.num || 0)) + 1;

function udalitChast(p) {
  const deti = model.parts.filter((x) => x.parent === p.id);
  if (!confirm(`Удалить «${p.name}»${deti.length ? ` вместе с вложенными (${deti.length})` : ''}?`)) return;
  const ubrat = new Set([p.id]);
  let est = true;
  while (est) {
    est = false;
    for (const x of model.parts) if (x.parent && ubrat.has(x.parent) && !ubrat.has(x.id)) { ubrat.add(x.id); est = true; }
  }
  model.parts = model.parts.filter((x) => !ubrat.has(x.id));
  model.animations = (model.animations || []).filter((a) => !ubrat.has(a.target));
  vybrannaya = null;
  izmenit();
}

$('#b-dobavit-chast').onclick = () => {
  const id = unikalnyId('detal');
  model.parts.push({ id, num: svobodnyNomer(), name: 'Новая деталь', desc: '', parent: vybrannaya || model.parts[0]?.id || null,
    shape: { type: 'box', size: [0.5, 0.5, 0.5] }, color: '#7f9bb5', position: [0, 0, 0], explode: { dir: [0, 1, 0], dist: 0.5 } });
  vybrannaya = id;
  izmenit();
};

$('#m-name').oninput = (e) => { model.name = e.target.value; izmenit(true); };
$('#m-scale').oninput = (e) => { model.scale = { ...(model.scale || {}), text: e.target.value }; izmenit(true); };

// ---------- Анимации ----------
function narisovatAnimacii() {
  const box = $('#spisok-anim');
  box.innerHTML = '';
  if (!model.animations?.length) box.append(el('p', { class: 'podskazka' }, 'Анимаций пока нет.'));
  for (const a of model.animations || []) {
    const par = el('textarea', { class: 'kod', spellcheck: 'false' });
    par.value = JSON.stringify(a.params || {}, null, 1);
    par.oninput = () => {
      try { a.params = JSON.parse(par.value); par.style.borderColor = ''; izmenit(true); }
      catch { par.style.borderColor = '#c0392b'; }
    };
    box.append(el('div', { class: 'kartochka' },
      el('label', {}, 'Название', el('input', { value: a.name, oninput: (e) => { a.name = e.target.value; izmenit(true); } })),
      el('div', { class: 'dva' },
        el('label', {}, 'Тип', el('select', { onchange: (e) => { a.type = e.target.value; izmenit(true); } },
          Object.entries(ANIMACII).map(([k, v]) => el('option', { value: k, selected: k === a.type }, v.nazvanie)))),
        el('label', {}, 'Цель', el('select', { onchange: (e) => { a.target = e.target.value; izmenit(true); } },
          model.parts.map((p) => el('option', { value: p.id, selected: p.id === a.target }, p.name))))),
      el('label', { class: 'rezhim' }, el('input', { type: 'checkbox', checked: !!a.autoplay, onchange: (e) => { a.autoplay = e.target.checked; izmenit(true); } }), ' Включена сразу'),
      el('label', {}, 'Параметры', par),
      el('div', { class: 'knopki' }, el('button', { onclick: () => { model.animations = model.animations.filter((x) => x !== a); narisovatAnimacii(); izmenit(true); } }, 'Удалить')),
    ));
  }
}

$('#b-dobavit-anim').onclick = () => {
  model.animations = model.animations || [];
  let i = model.animations.length + 1;
  while (model.animations.some((a) => a.id === 'anim-' + i)) i++;
  model.animations.push({ id: 'anim-' + i, name: 'Вращение', type: 'rotate', target: vybrannaya || model.parts[0].id, params: { axis: [0, 1, 0], speed: 45 } });
  narisovatAnimacii();
  izmenit(true);
};

// ---------- Текст описания ----------
$('#b-primenit').onclick = () => {
  let m;
  try { m = JSON.parse($('#json').value); } catch (e) { soobshchit('Текст не читается как описание: ' + e.message, true); return; }
  const osh = proverit(m);
  if (osh.length) { soobshchit('В описании ошибки:\n' + osh.slice(0, 8).join('\n'), true); return; }
  izmeneno = true;
  ustanovitModel(m);
  soobshchit('Применено.');
};

// ---------- Вкладки ----------
for (const b of document.querySelectorAll('.vkladki button')) {
  b.onclick = () => {
    document.querySelectorAll('.vkladki button').forEach((x) => x.classList.toggle('akt', x === b));
    document.querySelectorAll('.vkladka').forEach((v) => v.classList.toggle('akt', v.id === 'v-' + b.dataset.v));
    if (b.dataset.v === 'tekst') $('#json').value = JSON.stringify(model, null, 2);
  };
}

// ---------- Новая, открыть, сохранить, скачать ----------
$('#spisok-modeley').onchange = (e) => otkryt(e.target.value).catch((er) => soobshchit(er.message, true));

$('#b-novaya').onclick = () => {
  if (izmeneno && !confirm('Есть несохранённые изменения. Начать новую модель?')) return;
  const id = 'model-' + Date.now().toString(36);
  istochnik = { gde: server ? 'server' : 'brauzer', id, novaya: true };
  vybrannaya = null;
  ustanovitModel({
    format: 1, id, name: 'Новая модель', scale: { text: '' },
    parts: [
      { id: 'koren', name: 'Основа', parent: null, shape: { type: 'group' }, position: [0, 0, 0] },
      { id: 'detal-1', num: 1, name: 'Деталь', desc: '', parent: 'koren', shape: { type: 'box', size: [1, 1, 1] }, color: '#7f9bb5', position: [0, 0.5, 0], explode: { dir: [0, 1, 0], dist: 1 } },
    ],
    animations: [],
  }, { sbrosKamery: true });
  pokazatIstochniki(null);
  izmeneno = true;
};

$('#b-otkryt').onclick = () => $('#f-otkryt').click();
$('#f-otkryt').onchange = async (e) => {
  const f = e.target.files[0];
  e.target.value = '';
  if (!f) return;
  let m;
  try { m = JSON.parse(await f.text()); } catch { soobshchit('Файл не читается как описание модели.', true); return; }
  const osh = proverit(m);
  if (osh.length) { soobshchit('В файле ошибки:\n' + osh.slice(0, 8).join('\n'), true); return; }
  m.id = m.id || 'model-' + Date.now().toString(36);
  istochnik = { gde: server ? 'server' : 'brauzer', id: m.id, novaya: true };
  vybrannaya = null;
  ustanovitModel(m, { sbrosKamery: true });
  pokazatIstochniki(null);
  izmeneno = true;
  soobshchit('Файл открыт. Нажмите «Сохранить», чтобы он остался в списке.');
};

async function sohranit({ tikho = false } = {}) {
  const osh = proverit(model);
  if (osh.length) { soobshchit('Сначала исправьте ошибки:\n' + osh.slice(0, 6).join('\n'), true); return; }
  // Образцы не перезаписываем — сохраняем копию.
  if (!istochnik || istochnik.gde === 'vstroennaya') istochnik = { gde: server ? 'server' : 'brauzer', id: model.id || 'model-' + Date.now().toString(36) };
  model.id = istochnik.id;
  if (server) versiya = (await api('models/' + encodeURIComponent(model.id), { method: 'PUT', body: { model } })).version;
  else { const l = lokalnye(); l[model.id] = model; localStorage.setItem(LOKALNYE, JSON.stringify(l)); }
  izmeneno = false;
  await zagruzitSpisok(`${istochnik.gde}:${istochnik.id}`);
  if (!tikho) soobshchit('Сохранено.');
  if (server?.chat) chatOkno?.pokazat(model.id);
}

// Claude поправил файл модели — показываем его версию, с тем же поворотом камеры.
let sveryaem = false;
async function sverit() {
  if (sveryaem || !server?.chat || istochnik?.gde !== 'server' || istochnik.novaya) return;
  sveryaem = true;
  try {
    const { v } = await api(`models/${encodeURIComponent(istochnik.id)}/versiya`);
    if (!v || v === versiya) return;
    if (izmeneno && !confirm('Claude поправил эту модель, а у вас есть несохранённые правки. Показать его версию? Ваши правки пропадут.')) {
      versiya = v;
      return;
    }
    let zapis;
    try {
      zapis = await api('models/' + encodeURIComponent(istochnik.id));
    } catch (e) { versiya = v; soobshchit(e.message, true); return; }
    versiya = zapis.version;
    const osh = proverit(zapis.model);
    if (osh.length) { soobshchit('Новая версия модели с ошибками, показываю прежнюю:\n' + osh.slice(0, 6).join('\n'), true); return; }
    if (vybrannaya && !zapis.model.parts.some((p) => p.id === vybrannaya)) vybrannaya = null;
    ustanovitModel(zapis.model);
    izmeneno = false;
    await zagruzitSpisok(`server:${istochnik.id}`);
    soobshchit('Модель обновлена.');
  } catch { /* связь пропала — проверим в следующий раз */ } finally { sveryaem = false; }
}
$('#b-sohranit').onclick = () => sohranit().catch((e) => soobshchit('Не сохранилось: ' + e.message, true));

const skachat = (blob, imya) => {
  const a = el('a', { href: URL.createObjectURL(blob), download: imya });
  document.body.append(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 2000);
};
$('#b-skachat').onclick = () => skachat(new Blob([JSON.stringify(model, null, 2)], { type: 'application/json' }), `${model.id || 'model'}.json`);

window.addEventListener('beforeunload', (e) => { if (izmeneno) e.preventDefault(); });

// ---------- Предпросмотр и экспорт ----------
const adresProsmotra = () => server?.viewerUrl || 'https://mokeevasky.ru/glavpryg/model-3d/parashyutnaya-sistema/';

$('#b-predprosmotr').onclick = async () => {
  if (proverit(model).length) { soobshchit('Сначала исправьте ошибки в описании.', true); return; }
  const html = await sobratVBrauzere(model);
  const ramka = $('#ramka');
  ramka.srcdoc = html;
  $('#kod-vstavki').value = `<iframe src="${adresProsmotra()}" width="100%" height="560" style="border:0" loading="lazy" title="${(model.name || '').replace(/"/g, '')}"></iframe>`;
  $('#okno').hidden = false;
  razmerRamki('1280x720');
};
function razmerRamki(r) {
  const [w, h] = r.split('x');
  const ramka = $('#ramka');
  ramka.style.width = w + 'px';
  ramka.style.height = h + 'px';
  document.querySelectorAll('.razmery button').forEach((b) => b.classList.toggle('akt', b.dataset.r === r));
}
document.querySelectorAll('.razmery button').forEach((b) => { b.onclick = () => razmerRamki(b.dataset.r); });
$('#b-zakryt').onclick = () => { $('#okno').hidden = true; $('#ramka').srcdoc = ''; };
$('#kod-vstavki').onclick = (e) => e.target.select();

$('#b-eksport').onclick = async () => {
  if (proverit(model).length) { soobshchit('Сначала исправьте ошибки в описании.', true); return; }
  const html = await sobratVBrauzere(model);
  const fayl = new Blob([html], { type: 'text/html' });
  skachat(fayl, `${model.id || 'model'}.html`);
  let tekst = 'Готов файл просмотрщика. Его выкладывают на открытый адрес как главную страницу (index.html).';
  if (server) {
    try {
      const r = await fetch(`api/exports/${encodeURIComponent(model.id)}?name=${encodeURIComponent(model.name || '')}`, { method: 'PUT', headers: { 'content-type': 'text/html' }, body: fayl });
      if (!r.ok) throw new Error((await r.json().catch(() => null))?.error || `ошибка ${r.status}`);
      await pokazatEksporty();
      tekst += ' Копия сохранена в «Материалах».';
    } catch (e) { tekst += ' Копию сохранить не удалось: ' + e.message; }
  }
  soobshchit(tekst, false, true);
};

async function pokazatEksporty() {
  const ul = $('#eksporty');
  ul.innerHTML = '';
  if (!server) return;
  const { exports: spisok } = await api('exports');
  if (!spisok.length) ul.append(el('li', {}, 'Пока нет ни одного.'));
  for (const e of spisok) {
    ul.append(el('li', {},
      el('a', { href: `api/exports/${encodeURIComponent(e.id)}`, download: `${e.id}.html` }, e.name || e.id),
      el('span', { class: 'id' }, new Date(e.updated).toLocaleString('ru-RU', { timeZone: 'Europe/Moscow', dateStyle: 'short', timeStyle: 'short' }) + ' МСК')));
  }
}

// ---------- Видео и GLB ----------
$('#b-video').onclick = async () => {
  if (!prosmotr) return;
  const sek = 8;
  const w = 1280;
  const h = 720;
  const holst = el('canvas', { width: w, height: h });
  const ctx = holst.getContext('2d');
  const tip = ['video/mp4;codecs=avc1', 'video/mp4', 'video/webm;codecs=vp9', 'video/webm'].find((t) => MediaRecorder.isTypeSupported(t));
  if (!tip) { soobshchit('Этот браузер не умеет записывать видео.', true); return; }
  const zapis = new MediaRecorder(holst.captureStream(30), { mimeType: tip, videoBitsPerSecond: 6e6 });
  const kuski = [];
  zapis.ondataavailable = (e) => e.data.size && kuski.push(e.data);
  const konec = new Promise((r) => { zapis.onstop = r; });
  $('#b-video').disabled = true;
  soobshchit(`Записываю видео ${sek} секунд, модель медленно поворачивается…`, false, true);
  prosmotr.avtoPovorot(true, 3);
  zapis.start();
  const t0 = performance.now();
  await new Promise((gotovo) => {
    const kadr = () => {
      // Кадр сцены вписываем в 16:9 без искажений.
      const k = prosmotr.kanva;
      // Тот же спокойный фон, что в просмотрщике.
      const fon = ctx.createLinearGradient(0, 0, 0, h);
      fon.addColorStop(0, '#cfe0ee');
      fon.addColorStop(0.6, '#eef3f7');
      fon.addColorStop(1, '#f7f8f6');
      ctx.fillStyle = fon;
      ctx.fillRect(0, 0, w, h);
      const m = Math.min(w / k.width, h / k.height);
      ctx.save();
      ctx.translate((w - k.width * m) / 2, (h - k.height * m) / 2);
      prosmotr.narisovatKadr(ctx, k.width * m, k.height * m);
      ctx.restore();
      if (performance.now() - t0 < sek * 1000) requestAnimationFrame(kadr); else gotovo();
    };
    kadr();
  });
  zapis.stop();
  await konec;
  prosmotr.avtoPovorot(false);
  $('#b-video').disabled = false;
  skachat(new Blob(kuski, { type: tip }), `${model.id || 'model'}.${tip.includes('mp4') ? 'mp4' : 'webm'}`);
  soobshchit('Видео готово.');
};

$('#b-glb').onclick = async () => {
  if (!prosmotr) return;
  const { GLTFExporter } = await import('./vendor/gltf-exporter.min.js');
  prosmotr.ustanovitVzryv(0);
  const glb = await new GLTFExporter().parseAsync(prosmotr.modelKoren, { binary: true });
  skachat(new Blob([glb], { type: 'model/gltf-binary' }), `${model.id || 'model'}.glb`);
  soobshchit('GLB готов: в нём форма и цвета, без анимаций и номеров.', false, true);
};

// ---------- По фото ----------
async function szhat(fayl) {
  const bmp = await createImageBitmap(fayl);
  const k = Math.min(1, 1568 / Math.max(bmp.width, bmp.height));
  const holst = el('canvas', { width: Math.round(bmp.width * k), height: Math.round(bmp.height * k) });
  const ctx = holst.getContext('2d');
  ctx.fillStyle = '#fff';
  ctx.fillRect(0, 0, holst.width, holst.height);
  ctx.drawImage(bmp, 0, 0, holst.width, holst.height);
  const blob = await new Promise((r) => holst.toBlob(r, 'image/jpeg', 0.85));
  return { prevyu: URL.createObjectURL(blob), blob, type: 'image/jpeg' };
}

function narisovatFoto() {
  const box = $('#foto-spisok');
  box.innerHTML = '';
  fotoNaZagruzku.forEach((f, i) => {
    box.append(el('div', { class: 'foto' },
      el('img', { src: f.prevyu, alt: '' }),
      el('button', { class: 'ubrat', title: 'Убрать', onclick: () => { fotoNaZagruzku.splice(i, 1); narisovatFoto(); } }, '×'),
      el('select', { onchange: (e) => { f.vid = e.target.value; } }, VIDY.map((v) => el('option', { value: v, selected: v === f.vid }, v)))));
  });
}

$('#f-foto').onchange = async (e) => {
  const fayly = [...e.target.files];
  e.target.value = '';
  const maks = server?.ai ? server.maxPhotos : (server?.maxStored ?? 8);
  for (const f of fayly) {
    if (fotoNaZagruzku.length >= maks) { soobshchit(`За один раз — не больше ${maks} фото.`, true); break; }
    try {
      const s = await szhat(f);
      fotoNaZagruzku.push({ ...s, vid: VIDY[Math.min(fotoNaZagruzku.length, 5)] });
    } catch { soobshchit(`Не получилось открыть «${f.name}» как картинку.`, true); }
  }
  narisovatFoto();
};

function pokazatIstochniki(zapis) {
  zapisModeli = zapis;
  const box = $('#istochniki');
  box.innerHTML = '';
  const foto = zapis?.source?.photos || [];
  if (!foto.length) return;
  for (const f of foto) {
    box.append(el('div', { class: 'foto' },
      el('img', { src: `api/photos/${encodeURIComponent(zapis.model.id)}/${f.n}`, alt: f.view }),
      el('div', { class: 'podskazka' }, f.view)));
  }
}

$('#b-foto-sohranit').onclick = async () => {
  if (!server) { soobshchit('Серверная часть не запущена — фото здесь не хранятся.', true); return; }
  if (!fotoNaZagruzku.length) { soobshchit('Добавьте хотя бы одно фото или схему.', true); return; }
  const b = $('#b-foto-sohranit');
  b.disabled = true;
  try {
    if (!istochnik || istochnik.gde !== 'server') await sohranit();
    const id = model.id;
    const svezhaya = await api('models/' + encodeURIComponent(id));
    const nachalo = Math.max(-1, ...(svezhaya.source?.photos || []).map((f) => f.n)) + 1;
    const novye = [];
    for (const [i, f] of fotoNaZagruzku.entries()) {
      const n = nachalo + i;
      b.textContent = `Загружаю ${i + 1} из ${fotoNaZagruzku.length}…`;
      const r = await fetch(`api/photos/${encodeURIComponent(id)}/${n}?view=${encodeURIComponent(f.vid)}`, { method: 'PUT', headers: { 'content-type': f.type }, body: f.blob });
      if (!r.ok) throw new Error((await r.json().catch(() => null))?.error || 'Фото не загрузилось.');
      novye.push({ n });
    }
    const zapis = await api(`models/${encodeURIComponent(id)}/materialy`, { method: 'POST', body: {
      photos: novye,
      size: $('#g-size').value.trim(),
      mode: document.querySelector('[name=g-mode]:checked').value,
    } });
    pokazatIstochniki(zapis);
    fotoNaZagruzku = [];
    narisovatFoto();
    soobshchit('Фото сохранены к модели.');
  } catch (e) {
    soobshchit(e.message, true);
  } finally {
    b.disabled = false;
    b.textContent = 'Сохранить к модели';
  }
};

$('#b-sozdat').onclick = async () => {
  if (!server) { soobshchit('Серверная часть не запущена — создание по фото недоступно.', true); return; }
  if (!server.ai) { soobshchit('ИИ не подключён: ключ доступа ещё не внесён в настройки.', true); return; }
  if (!fotoNaZagruzku.length) { soobshchit('Добавьте хотя бы одно фото или схему.', true); return; }
  const razmer = $('#g-size').value.trim();
  if (!razmer) { soobshchit('Укажите один реальный размер — по нему считается масштаб.', true); return; }
  if (izmeneno && !confirm('Текущая модель не сохранена. Создать новую по фото?')) return;
  const b = $('#b-sozdat');
  b.disabled = true;
  b.textContent = 'ИИ составляет описание… (до пары минут)';
  try {
    // Сначала фото по одному — так сервер не разбирает тяжёлые запросы.
    const id = 'model-' + Date.now().toString(36);
    for (const [n, f] of fotoNaZagruzku.entries()) {
      b.textContent = `Загружаю фото ${n + 1} из ${fotoNaZagruzku.length}…`;
      const r = await fetch(`api/photos/${id}/${n}?view=${encodeURIComponent(f.vid)}`, { method: 'PUT', headers: { 'content-type': f.type }, body: f.blob });
      if (!r.ok) throw new Error((await r.json().catch(() => null))?.error || 'Фото не загрузилось.');
    }
    b.textContent = 'ИИ составляет описание… (до пары минут)';
    const zapis = await api('generate', { method: 'POST', body: {
      id,
      name: $('#g-name').value.trim() || 'Новая модель',
      size: razmer,
      mode: document.querySelector('[name=g-mode]:checked').value,
      photos: fotoNaZagruzku.map((f, n) => ({ n, view: f.vid })),
    } });
    istochnik = { gde: 'server', id: zapis.model.id };
    vybrannaya = null;
    ustanovitModel(zapis.model, { sbrosKamery: true });
    pokazatIstochniki(zapis);
    fotoNaZagruzku = [];
    narisovatFoto();
    izmeneno = false;
    await zagruzitSpisok(`server:${zapis.model.id}`);
    soobshchit('Модель создана и сохранена. Её можно поправить словами или вручную.', false, true);
  } catch (e) {
    soobshchit(e.message, true);
  } finally {
    b.disabled = false;
    b.textContent = 'Создать модель';
    await uznatServer();
  }
};

$('#b-pravka').onclick = async () => {
  const tekst = $('#g-pravka').value.trim();
  if (!tekst) { soobshchit('Напишите, что поправить: например, «купол выше».', true); return; }
  if (!server?.ai) { soobshchit('ИИ не подключён — правку словами сделать нельзя, можно поправить вручную.', true); return; }
  const b = $('#b-pravka');
  b.disabled = true;
  b.textContent = 'ИИ правит…';
  try {
    if (!istochnik || istochnik.gde !== 'server') await sohranit();
    const zapis = await api('refine', { method: 'POST', body: { id: model.id, instruction: tekst, model } });
    ustanovitModel(zapis.model);
    izmeneno = false;
    $('#g-pravka').value = '';
    soobshchit('Поправлено и сохранено.');
  } catch (e) {
    soobshchit(e.message, true);
  } finally {
    b.disabled = false;
    b.textContent = 'Поправить';
    await uznatServer();
  }
};

// ---------- Запуск ----------
await uznatServer();
await zagruzitSpisok();
const pervaya = ['server:parashyut', 'vstroennaya:parashyut'].find((k) => $('#spisok-modeley').querySelector(`option[value="${k}"]`)) || $('#spisok-modeley').value;
$('#spisok-modeley').value = pervaya;
if (server?.chat) {
  $('#vkl-chat').hidden = false;
  $('#b-spisok').hidden = false;
  $('#na-sayt').hidden = false;
  chatOkno = sozdatChat({
    szhat,
    soobshchit,
    sverit,
    pokazatIstochniki,
    // Перед сообщением всё сохраняем, чтобы Claude видел то же, что и вы.
    gotovaModel: async () => {
      if (izmeneno || !istochnik || istochnik.gde !== 'server' || istochnik.novaya) {
        await sohranit({ tikho: true });
        if (istochnik) delete istochnik.novaya;
      }
      return model.id;
    },
  });
  $('#vkl-chat').click();
  $('#b-spisok').onclick = (e) => {
    const skryt = document.body.classList.toggle('skryt-spisok');
    e.target.textContent = skryt ? 'Показать список' : 'Скрыть список';
  };
  setInterval(sverit, 8000);
}
await otkryt(pervaya);
await pokazatEksporty().catch((e) => soobshchit(e.message, true));
