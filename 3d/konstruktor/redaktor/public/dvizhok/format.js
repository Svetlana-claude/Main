// Формат файла-описания модели и его проверка.
// Модуль без зависимостей: его используют и движок в браузере, и серверная функция.

export const VERSIYA_FORMATA = 1;

// Формы деталей, которые умеет строить движок. Размеры — в метрах.
export const FORMY = {
  group: 'узел без своей формы',
  box: 'брусок: size [x, y, z]',
  cylinder: 'цилиндр: radiusTop, radiusBottom, height, segments',
  cone: 'конус: radius, height',
  sphere: 'шар: radius; вытянуть — через scale детали',
  capsule: 'капсула: radius, length',
  torus: 'кольцо: radius, tube, arc (градусы)',
  lathe: 'тело вращения вокруг Y: points [[r, y], …]',
  tube: 'трубка по точкам: points [[x, y, z], …] в общих координатах, radius',
  wing: 'крыло/плоскость с профилем: span, chord, thickness, taper, sweep, dihedral',
  kupol: 'купол парашюта: vid "krylo" | "kruglyy", sections, divisions, span, chord, arc, thickness (или diameter, height для круглого)',
  chelovek: 'фигура человека: height, pose "visit" | "stoit" | "sidit"',
  lines: 'набор строп/тросов: from и to — "деталь:якорь" или список таких ссылок; map "nearest" (к ближайшей точке) | "paired" (по порядку); labelIndex, labelAt — где на линиях ставить номер',
};

// Типы анимаций. control — как ею управлять в просмотрщике.
export const ANIMACII = {
  swing: { nazvanie: 'раскачка (маятник)', control: 'knopka' },
  rotate: { nazvanie: 'вращение', control: 'knopka' },
  breathe: { nazvanie: 'дыхание (волна по сетке)', control: 'knopka' },
  unfold: { nazvanie: 'раскрытие 0–1', control: 'polzunok' },
  control: { nazvanie: 'управление (поворот)', control: 'polzunok-pm' },
  jitter: { nazvanie: 'дрожание', control: 'knopka' },
  descent: { nazvanie: 'снижение', control: 'knopka' },
};

function vec3(v) {
  return Array.isArray(v) && v.length === 3 && v.every((x) => typeof x === 'number' && Number.isFinite(x));
}

// Проверка описания. Возвращает список понятных ошибок (пустой — всё хорошо).
export function proverit(model) {
  const oshibki = [];
  if (!model || typeof model !== 'object') return ['Описание пустое или это не объект.'];
  if (!model.name) oshibki.push('Нет названия модели (name).');
  if (!Array.isArray(model.parts) || model.parts.length === 0) {
    oshibki.push('Нет списка частей (parts).');
    return oshibki;
  }
  const ids = new Map();
  const nomera = new Map();
  for (const [i, p] of model.parts.entries()) {
    const gde = `Часть №${i + 1}${p && p.id ? ` (${p.id})` : ''}`;
    if (!p || typeof p !== 'object') { oshibki.push(`${gde}: не объект.`); continue; }
    if (!p.id || typeof p.id !== 'string') oshibki.push(`${gde}: нет id.`);
    else if (ids.has(p.id)) oshibki.push(`${gde}: id «${p.id}» повторяется.`);
    else ids.set(p.id, p);
    if (!p.name) oshibki.push(`${gde}: нет названия.`);
    if (p.num != null) {
      if (!Number.isInteger(p.num) || p.num < 1) oshibki.push(`${gde}: номер должен быть целым от 1.`);
      else if (nomera.has(p.num)) oshibki.push(`${gde}: номер ${p.num} уже занят частью «${nomera.get(p.num)}».`);
      else nomera.set(p.num, p.id);
    }
    const tip = p.shape && p.shape.type;
    if (!tip) oshibki.push(`${gde}: не указана форма (shape.type).`);
    else if (!FORMY[tip]) oshibki.push(`${gde}: неизвестная форма «${tip}».`);
    if (p.position != null && !vec3(p.position)) oshibki.push(`${gde}: position — три числа.`);
    if (p.rotation != null && !vec3(p.rotation)) oshibki.push(`${gde}: rotation — три числа (градусы).`);
    if (p.scale != null && !vec3(p.scale)) oshibki.push(`${gde}: scale — три числа.`);
    if (p.explode != null) {
      if (!vec3(p.explode.dir)) oshibki.push(`${gde}: explode.dir — три числа.`);
      if (typeof p.explode.dist !== 'number') oshibki.push(`${gde}: explode.dist — число (метры).`);
    }
  }
  // Родители и циклы.
  for (const p of model.parts) {
    if (!p || !p.id) continue;
    if (p.parent != null && !ids.has(p.parent)) oshibki.push(`Часть ${p.id}: родитель «${p.parent}» не найден.`);
    const vidennye = new Set([p.id]);
    let tek = p;
    while (tek && tek.parent != null) {
      if (vidennye.has(tek.parent)) { oshibki.push(`Часть ${p.id}: родители замкнулись в круг.`); break; }
      vidennye.add(tek.parent);
      tek = ids.get(tek.parent);
    }
  }
  // Ссылки строп на детали.
  for (const p of model.parts) {
    if (!p || !p.shape || p.shape.type !== 'lines') continue;
    for (const kon of ['from', 'to']) {
      const ssylki = Array.isArray(p.shape[kon]) ? p.shape[kon] : [p.shape[kon]];
      for (const s of ssylki) {
        const detal = typeof s === 'string' ? s.split(':')[0] : null;
        if (!detal || !ids.has(detal)) oshibki.push(`Часть ${p.id}: ${kon} ссылается на неизвестную деталь «${s}».`);
      }
    }
  }
  // Анимации.
  const animIds = new Set();
  for (const [i, a] of (model.animations || []).entries()) {
    const gde = `Анимация №${i + 1}${a && a.id ? ` (${a.id})` : ''}`;
    if (!a || typeof a !== 'object') { oshibki.push(`${gde}: не объект.`); continue; }
    if (!a.id) oshibki.push(`${gde}: нет id.`);
    else if (animIds.has(a.id)) oshibki.push(`${gde}: id повторяется.`);
    else animIds.add(a.id);
    if (!a.name) oshibki.push(`${gde}: нет названия.`);
    if (!ANIMACII[a.type]) oshibki.push(`${gde}: неизвестный тип «${a.type}».`);
    if (!a.target || !ids.has(a.target)) oshibki.push(`${gde}: цель «${a.target}» не найдена.`);
  }
  return oshibki;
}

// Список деталей для таблицы и номеров — из одного места.
export function spisokDetaley(model) {
  return (model.parts || [])
    .filter((p) => p.num != null)
    .sort((a, b) => a.num - b.num)
    .map((p) => ({ id: p.id, num: p.num, name: p.name, desc: p.desc || '' }));
}
