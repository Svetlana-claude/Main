// Закрытый редактор: страницы, хранилище моделей и фото, обращения к ИИ.
// Всё — только после проверки входа.

import { proveritVhod } from './dostup.js';
import { zagruzitFoto, sozdatPoFoto, popravit } from './ii.js';
import { proverit } from '../public/dvizhok/format.js';

const chislo = (v, d) => (Number.isFinite(+v) && +v > 0 ? +v : d);
const limity = (env) => ({
  limit: chislo(env.DAILY_LIMIT, 30),
  maxPhotos: chislo(env.MAX_PHOTOS, 8),
  maxPhotoMb: chislo(env.MAX_PHOTO_MB, 5),
});

const json = (dannye, status = 200) => new Response(JSON.stringify(dannye), {
  status,
  headers: { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' },
});
const oshibka = (tekst, status = 400) => json({ error: tekst }, status);

// Сутки — по Москве.
const segodnya = () => new Date(Date.now() + 3 * 3600 * 1000).toISOString().slice(0, 10);
const ID = /^[a-z0-9][a-z0-9-]{0,63}$/;

async function ispolzovanoSegodnya(env) {
  return +(await env.HRAN.get('limit:' + segodnya())) || 0;
}
async function uchestZapros(env) {
  const n = (await ispolzovanoSegodnya(env)) + 1;
  await env.HRAN.put('limit:' + segodnya(), String(n), { expirationTtl: 3 * 24 * 3600 });
}

async function zapis(env, id) {
  return env.HRAN.get('model:' + id, 'json');
}
async function sohranitZapis(env, z) {
  z.updated = new Date().toISOString();
  await env.HRAN.put('model:' + z.model.id, JSON.stringify(z), { metadata: { name: z.model.name, updated: z.updated } });
  return z;
}

// Долгий ответ: сразу начинаем отдавать пробелы, чтобы соединение не оборвалось,
// пока ИИ думает, а в конце дописываем JSON. Пробелы перед JSON ему не мешают.
function dolgiyOtvet(ctx, rabota) {
  const { readable, writable } = new TransformStream();
  const pisat = writable.getWriter();
  const enc = new TextEncoder();
  const puls = setInterval(() => pisat.write(enc.encode(' ')).catch(() => {}), 10000);
  ctx.waitUntil((async () => {
    let itog;
    try { itog = await rabota(); } catch (e) { itog = { error: e?.message || String(e) }; }
    clearInterval(puls);
    await pisat.write(enc.encode(JSON.stringify(itog)));
    await pisat.close();
  })());
  return new Response(readable, { headers: { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' } });
}

function soobshchenieOshibkiIi(e) {
  const s = e?.status;
  if (s === 401) return 'ИИ не принял ключ доступа. Проверьте ключ в настройках.';
  if (s === 429) return 'ИИ сейчас перегружен или исчерпан лимит на его стороне. Попробуйте через пару минут.';
  if (s === 400 && /credit|balance/i.test(e.message || '')) return 'На счёте ИИ закончились деньги — нужно пополнить баланс.';
  if (s >= 500) return 'ИИ временно недоступен. Попробуйте позже.';
  return e?.message || 'Неизвестная ошибка ИИ.';
}

async function api(request, env, ctx, put, vhod) {
  const L = limity(env);
  const m = request.method;

  if (put === 'status' && m === 'GET') {
    return json({ ai: !!env.ANTHROPIC_API_KEY, used: await ispolzovanoSegodnya(env), ...L, email: vhod.email, viewerUrl: env.VIEWER_URL || null });
  }

  if (put === 'models' && m === 'GET') {
    const spisok = [];
    let cursor;
    do {
      const r = await env.HRAN.list({ prefix: 'model:', cursor });
      for (const k of r.keys) spisok.push({ id: k.name.slice(6), name: k.metadata?.name, updated: k.metadata?.updated });
      cursor = r.list_complete ? null : r.cursor;
    } while (cursor);
    spisok.sort((a, b) => String(b.updated).localeCompare(String(a.updated)));
    return json({ models: spisok });
  }

  let r = put.match(/^models\/([^/]+)$/);
  if (r) {
    const id = decodeURIComponent(r[1]);
    if (!ID.test(id)) return oshibka('Неправильный id модели: только латиница, цифры и дефис.');
    if (m === 'GET') {
      const z = await zapis(env, id);
      return z ? json(z) : oshibka('Модель не найдена.', 404);
    }
    if (m === 'PUT') {
      const telo = await request.json().catch(() => null);
      const model = telo?.model;
      const osh = proverit(model);
      if (osh.length) return oshibka('В описании ошибки:\n' + osh.slice(0, 6).join('\n'));
      model.id = id;
      const z = (await zapis(env, id)) || { model, source: null, history: [] };
      z.model = model;
      z.history = [...(z.history || []), { at: new Date().toISOString(), kind: 'save', who: vhod.email }].slice(-50);
      return json(await sohranitZapis(env, z));
    }
    if (m === 'DELETE') {
      const z = await zapis(env, id);
      for (const f of z?.source?.photos || []) await env.HRAN.delete(`photo:${id}:${f.n}`);
      await env.HRAN.delete('model:' + id);
      return json({ ok: true });
    }
  }

  r = put.match(/^photos\/([^/]+)\/(\d+)$/);
  if (r) {
    const id = decodeURIComponent(r[1]);
    const n = +r[2];
    if (!ID.test(id)) return oshibka('Неправильный id модели.');
    if (m === 'GET') {
      const f = await env.HRAN.getWithMetadata(`photo:${id}:${n}`, 'stream');
      if (!f.value) return oshibka('Фото не найдено.', 404);
      return new Response(f.value, { headers: { 'content-type': f.metadata?.type || 'image/jpeg', 'cache-control': 'private, max-age=86400' } });
    }
    if (m === 'PUT') {
      if (n >= L.maxPhotos) return oshibka(`За один раз — не больше ${L.maxPhotos} фото.`);
      const tip = request.headers.get('content-type') || '';
      if (!/^image\/(jpeg|png|webp|gif)$/.test(tip)) return oshibka('Можно загружать только картинки: JPEG, PNG, WebP.');
      const razmer = +request.headers.get('content-length') || 0;
      if (!razmer || razmer > L.maxPhotoMb * 1024 * 1024) return oshibka(`Фото больше ${L.maxPhotoMb} МБ — уменьшите его.`);
      const vid = (new URL(request.url).searchParams.get('view') || 'вид не указан').slice(0, 40);
      // Тело кладётся в хранилище потоком, без разбора в коде.
      await env.HRAN.put(`photo:${id}:${n}`, request.body, { metadata: { type: tip, view: vid } });
      return json({ ok: true });
    }
  }

  if (put === 'generate' && m === 'POST') {
    if (!env.ANTHROPIC_API_KEY) return oshibka('ИИ не подключён: ключ доступа ещё не внесён в настройки.');
    const t = await request.json().catch(() => null);
    if (!t || !ID.test(t.id || '')) return oshibka('Нет id модели.');
    const foto = (t.photos || []).slice(0, L.maxPhotos);
    if (!foto.length) return oshibka('Нет ни одного фото.');
    if (!t.size) return oshibka('Укажите один реальный размер для масштаба.');
    if ((await ispolzovanoSegodnya(env)) >= L.limit) return oshibka(`На сегодня запросы к ИИ закончились (${L.limit} в день). Завтра лимит обновится.`);
    // Сначала убеждаемся, что все фото дошли, — только потом засчитываем запрос.
    const fayly = [];
    for (const f of foto) {
      const s = await env.HRAN.getWithMetadata(`photo:${t.id}:${+f.n}`, 'arrayBuffer');
      if (!s.value) return oshibka(`Фото №${+f.n + 1} не дошло до сервера — загрузите ещё раз.`);
      fayly.push({ f, s });
    }
    await uchestZapros(env);
    return dolgiyOtvet(ctx, async () => {
      const sobrannye = [];
      for (const { f, s } of fayly) {
        let fileId;
        try {
          fileId = await zagruzitFoto(env, { n: f.n, data: s.value, type: s.metadata?.type });
        } catch (e) { throw new Error(soobshchenieOshibkiIi(e)); }
        sobrannye.push({ n: f.n, view: s.metadata?.view || f.view, fileId });
      }
      let model;
      try {
        model = await sozdatPoFoto(env, { name: t.name || 'Новая модель', size: t.size, mode: t.mode, foto: sobrannye });
      } catch (e) { throw new Error(soobshchenieOshibkiIi(e)); }
      model.id = t.id;
      if (t.name) model.name = t.name;
      const z = {
        model,
        source: { mode: t.mode, size: t.size, photos: sobrannye.map(({ n, view, fileId }) => ({ n, view, fileId })) },
        history: [{ at: new Date().toISOString(), kind: 'generate', who: vhod.email }],
      };
      return sohranitZapis(env, z);
    });
  }

  if (put === 'refine' && m === 'POST') {
    if (!env.ANTHROPIC_API_KEY) return oshibka('ИИ не подключён: ключ доступа ещё не внесён в настройки.');
    const t = await request.json().catch(() => null);
    if (!t || !ID.test(t.id || '')) return oshibka('Нет id модели.');
    const pros = String(t.instruction || '').trim().slice(0, 1000);
    if (!pros) return oshibka('Напишите, что поправить.');
    if (proverit(t.model).length) return oshibka('Текущее описание с ошибками — сначала исправьте их.');
    if ((await ispolzovanoSegodnya(env)) >= L.limit) return oshibka(`На сегодня запросы к ИИ закончились (${L.limit} в день). Завтра лимит обновится.`);
    await uchestZapros(env);
    return dolgiyOtvet(ctx, async () => {
      let model;
      try { model = await popravit(env, { model: t.model, instruction: pros }); } catch (e) { throw new Error(soobshchenieOshibkiIi(e)); }
      model.id = t.id;
      const z = (await zapis(env, t.id)) || { source: null, history: [] };
      z.model = model;
      z.history = [...(z.history || []), { at: new Date().toISOString(), kind: 'refine', text: pros, who: vhod.email }].slice(-50);
      return sohranitZapis(env, z);
    });
  }

  return oshibka('Нет такой функции.', 404);
}

export default {
  async fetch(request, env, ctx) {
    const vhod = await proveritVhod(request, env);
    if (!vhod) {
      return new Response('Доступ закрыт. Войдите через страницу входа.', {
        status: 403,
        headers: { 'content-type': 'text/plain; charset=utf-8', 'cache-control': 'no-store', 'x-robots-tag': 'noindex' },
      });
    }
    const url = new URL(request.url);
    if (url.pathname.startsWith('/api/')) return api(request, env, ctx, url.pathname.slice(5), vhod);
    const otvet = await env.ASSETS.fetch(request);
    const r = new Response(otvet.body, otvet);
    r.headers.set('x-robots-tag', 'noindex, nofollow');
    r.headers.set('cache-control', 'no-store');
    return r;
  },
};
