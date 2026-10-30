// Обращение к ИИ: по фото и схемам составить описание модели и поправить
// его словами. Ключ доступа берётся только из защищённых настроек Cloudflare
// (env.ANTHROPIC_API_KEY) — в коде и в браузере его нет.

import Anthropic, { toFile } from '@anthropic-ai/sdk';
import { proverit, FORMY, ANIMACII } from '../public/dvizhok/format.js';

const PARAMETRY_ANIMACIY = {
  swing: 'amplitude (градусы), period (с), axis [x,y,z], pivot [x,y,z] — точка подвеса качания',
  rotate: 'axis [x,y,z], speed (градусы/с), pivot — необязательно',
  breathe: 'amplitude (м), speed (раз/с), wavelength (м), axis "x"|"y"|"z" — только для форм kupol',
  unfold: 'default 0..1, fromScale [x,y,z] — масштаб в сложенном виде, fromOffset [x,y,z] — сдвиг в сложенном виде',
  control: 'yawSpeed (градусы/с), bank (градусы), pivot, pulls [{part, offset [x,y,z], side "left"|"right"}], flap {part, amount}',
  jitter: 'amplitude (градусы), speed, offset (м)',
  descent: 'speed (м/с), bob (м)',
};

const PRAVILA = `Ты составляешь файл-описание 3D-модели для движка показа на three.js.
Ответ — только JSON-объект, без пояснений и без markdown.

Формат:
{
  "format": 1,
  "id": "латиница-через-дефис",
  "name": "Название по-русски",
  "scale": { "text": "один реальный размер, например «Размах купола 8 м»", "part": "id детали", "size": число },
  "view": { "camera": [x,y,z], "target": [x,y,z] },
  "parts": [ { "id", "num", "name", "desc", "parent", "shape": { "type", ... }, "color": "#rrggbb",
               "position": [x,y,z], "rotation": [градусы], "scale": [x,y,z], "label": [x,y,z],
               "anchors": { "имя": [[x,y,z], ...] }, "explode": { "dir": [x,y,z], "dist": метры } } ],
  "animations": [ { "id", "name", "type", "target", "autoplay": true|false, "params": { ... } } ]
}

Координаты: метры, ось Y вверх, передняя сторона предмета смотрит в +Z, правая сторона предмета — в −X.
Начало координат — главная точка подвеса или опоры. position, label, anchors, pivot и точки
трубок (tube.points) — в общих координатах собранной модели, а не относительно родителя.
Размеры формы (size, radius, span и т. д.) — в метрах, в собственных осях детали.

Вложенность: корень → узлы → детали. У каждой части есть id и родитель (у корня parent: null).
Дети двигаются вместе с родителем — и при анимации, и при разборке.

Номера: у видимых деталей num — целые числа с 1 без пропусков, сверху вниз или от главного к второстепенному.
У вспомогательных узлов и мелких повторяющихся частей num нет — их подсветка идёт через родителя.
name — коротко, desc — одно-два простых предложения по-русски: что это и зачем.

Разборка (explode): dir — куда деталь отходит, dist — на сколько метров относительно родителя.
Подбери так, чтобы в разобранном виде детали не перекрывали друг друга.

Формы:
${Object.entries(FORMY).map(([k, v]) => `- ${k}: ${v}`).join('\n')}
У форм kupol есть якоря "kromka" (точки крепления строп) и "khvost" (задняя кромка),
у chelovek — "ruki". Свои якоря задаются в anchors.

Анимации (type — параметры):
${Object.entries(ANIMACII).map(([k, v]) => `- ${k} (${v.nazvanie}): ${PARAMETRY_ANIMACIY[k]}`).join('\n')}
Добавь 2–4 уместные анимации, если у предмета есть подвижные части.

Масштаб: пользователь даёт один реальный размер — подгони под него все размеры.
Не выдумывай деталей, которых не видно и которых у такого предмета не бывает. Если часть
не видна, но наверняка есть — сделай правдоподобно и напиши в desc «предположительно».
Обычно хватает 5–25 частей.`;

const REZHIMY = {
  shema: 'Режим «по схеме»: виды — чертежи одного предмета. Совмещай виды между собой и снимай размеры по ним как можно точнее.',
  foto: 'Режим «по фото»: это обычные фотографии, пропорции оценивай приблизительно, перспективу учитывай.',
};

function vynutJson(tekst) {
  const a = tekst.indexOf('{');
  const b = tekst.lastIndexOf('}');
  if (a < 0 || b <= a) throw new Error('ИИ ответил не описанием модели. Попробуйте ещё раз.');
  return JSON.parse(tekst.slice(a, b + 1));
}

function klient(env) {
  return new Anthropic({ apiKey: env.ANTHROPIC_API_KEY, ...(env.ANTHROPIC_BASE_URL ? { baseURL: env.ANTHROPIC_BASE_URL } : {}) });
}

async function sprosit(env, system, content) {
  const c = klient(env);
  const otvet = await c.beta.messages.create({
    model: env.AI_MODEL || 'claude-opus-5-5',
    max_tokens: 21000,
    output_config: { effort: env.AI_EFFORT || 'high' },
    betas: ['server-side-fallback-2026-07-01'],
    fallbacks: 'default',
    system,
    messages: [{ role: 'user', content }],
  });
  if (otvet.stop_reason === 'refusal') throw new Error('ИИ отказался составлять описание по этим изображениям.');
  if (otvet.stop_reason === 'max_tokens') throw new Error('Ответ ИИ оборвался — модель получилась слишком большой. Попробуйте меньше фото или проще предмет.');
  const tekst = otvet.content.filter((b) => b.type === 'text').map((b) => b.text).join('');
  return { tekst, usage: otvet.usage };
}

// Описание по ответу ИИ; если формат с ошибками — один раз просим исправить.
async function poluchitModel(env, system, content) {
  let { tekst } = await sprosit(env, system, content);
  let model;
  let oshibki;
  try {
    model = vynutJson(tekst);
    oshibki = proverit(model);
  } catch (e) {
    oshibki = ['JSON не читается: ' + e.message];
  }
  if (oshibki.length) {
    ({ tekst } = await sprosit(env, system, [
      ...content,
      { type: 'text', text: `Твой прошлый ответ:\n${tekst}\n\nВ нём ошибки:\n${oshibki.join('\n')}\nВерни исправленный JSON целиком.` },
    ]));
    model = vynutJson(tekst);
    oshibki = proverit(model);
    if (oshibki.length) throw new Error('ИИ вернул описание с ошибками:\n' + oshibki.slice(0, 5).join('\n'));
  }
  return model;
}

// Загрузить фото в хранилище файлов ИИ (90 дней), чтобы не гонять их через код.
export async function zagruzitFoto(env, foto) {
  const c = klient(env);
  const f = await c.files.upload({
    file: await toFile(foto.data, `foto-${foto.n}.jpg`, { type: foto.type || 'image/jpeg' }),
    expires_in_seconds: 90 * 24 * 3600,
  });
  return f.id;
}

export async function sozdatPoFoto(env, { name, size, mode, foto }) {
  const content = [];
  for (const f of foto) {
    content.push({ type: 'text', text: `Вид: ${f.view}` });
    content.push({ type: 'image', source: { type: 'file', file_id: f.fileId } });
  }
  content.push({ type: 'text', text: `${REZHIMY[mode] || REZHIMY.foto}\nНазвание модели: ${name}\nРеальный размер для масштаба: ${size}\nСоставь описание модели.` });
  return poluchitModel(env, PRAVILA, content);
}

export async function popravit(env, { model, instruction }) {
  const system = PRAVILA + `\n\nТебе дают текущее описание и просьбу его поправить. Верни полное исправленное описание целиком.
Меняй только то, о чём просят. id, номера и описания существующих деталей сохраняй, если просьба их не касается.`;
  return poluchitModel(env, system, [{ type: 'text', text: `Текущее описание:\n${JSON.stringify(model)}\n\nПросьба: ${instruction}` }]);
}
