// Окно разговора с Claude рядом с моделью. У каждой модели своя тема в проекте
// «3D-модели»; лента, отправка и поток ответа — те же адреса, что у тем на сайте.

const $ = (s) => document.querySelector(s);
const chislo = (n, a, b, c) => `${n} ${n % 10 === 1 && n % 100 !== 11 ? a : n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 10 || n % 100 >= 20) ? b : c}`;

export function sozdatChat({ szhat, soobshchit, sverit, pokazatIstochniki, gotovaModel }) {
  const lenta = $('#chat-lenta');
  const tekst = $('#chat-tekst');
  const knopka = $('#b-chat');
  const oshibka = $('#chat-oshibka');
  let id = null;          // какая модель
  let conv = null;        // её разговор
  let sost = null;        // адрес сайта и защита формы
  let potok = null;
  let skolko = 40;
  let prilozheno = [];    // [{ put, prevyu }]
  let chasy = null;

  const pokazatOshibku = (t) => { oshibka.textContent = t || ''; oshibka.hidden = !t; };
  const vnizu = () => lenta.scrollHeight - lenta.scrollTop - lenta.clientHeight < 120;
  const vniz = () => { lenta.scrollTop = lenta.scrollHeight; };
  const adres = (hvost) => `${sost.root}/chat/${conv}${hvost}`;
  const idet = (da) => {
    knopka.textContent = da ? 'Дописать' : 'Отправить';
    clearInterval(chasy);
    // Пока Claude работает, сверяемся с файлом модели чаще
    chasy = da ? setInterval(sverit, 2500) : null;
  };

  function zakryt() {
    potok?.close();
    potok = null;
    idet(false);
  }

  async function obnovit() {
    if (!conv) {
      lenta.innerHTML = '<p class="muted">Напишите, что сделать с этой моделью, или приложите фото и схемы. Модель обновится сама.</p>';
      return null;
    }
    const stick = vnizu();
    const r = await fetch(adres(`/feed?n=${skolko}`), { credentials: 'same-origin', cache: 'no-store' });
    if (!r.ok) throw new Error('Вход истёк — обновите страницу и войдите снова.');
    const d = await r.json();
    lenta.innerHTML = d.html;
    idet(d.running);
    if (stick) vniz();
    return d;
  }

  function slushat() {
    if (potok || !conv) return;
    const svoy = conv;
    potok = new EventSource(adres('/stream'));
    potok.onmessage = (e) => {
      if (svoy !== conv) return;
      const ev = JSON.parse(e.data);
      const live = $('#live-text');
      const status = $('#live-status');
      if (ev.t === 'snapshot' && live) {
        live.textContent = ev.x;
        if (status && ev.s) status.textContent = ev.s;
      } else if (ev.t === 'status') {
        if (status) status.textContent = ev.x;
        sverit();
      } else if (ev.t === 'start') {
        if (live) live.textContent = '';
      } else if (ev.t === 'delta') {
        const stick = vnizu();
        if (live) live.textContent += ev.x;
        if (stick) vniz();
      } else if (ev.t === 'added' || ev.t === 'saved') {
        obnovit().catch(() => {});
        sverit();
      } else if (ev.t === 'done') {
        potok.close();
        potok = null;
        obnovit().catch(() => {});
        sverit();
      }
    };
    potok.onerror = () => {
      potok?.close();
      potok = null;
      setTimeout(() => {
        if (svoy === conv) obnovit().then((d) => { if (d?.running) slushat(); }).catch(() => {});
      }, 2000);
    };
  }

  async function pokazat(novyy) {
    zakryt();
    id = novyy;
    conv = null;
    skolko = 40;
    prilozheno = [];
    narisovatPrilozheno();
    pokazatOshibku('');
    if (!id) { obnovit(); return; }
    try {
      const r = await fetch(`api/chat/${encodeURIComponent(id)}`, { cache: 'no-store' });
      const d = await r.json();
      if (!r.ok) throw new Error(d.error);
      if (id !== novyy) return;
      sost = d;
      conv = d.conv;
      await obnovit();
      vniz();
      if (d.running) slushat();
    } catch (e) { pokazatOshibku(e.message); }
  }

  function narisovatPrilozheno() {
    const box = $('#chat-prilozheno');
    box.innerHTML = '';
    // Снимки — справочный материал для Claude: здесь только строка «что приложено».
    for (const f of prilozheno) {
      const c = document.createElement('span');
      c.className = 'chip';
      c.textContent = f.podpis;
      c.title = f.puti.join(', ');
      box.append(c);
    }
  }

  // Браузер сам сожмёт только обычные снимки; архив, видео и HEIC разбирает сервер.
  const prostoeFoto = (f) => /^image\/(jpeg|png|webp|gif)$/.test(f.type);
  const hod = (t) => { const h = $('#chat-hod'); h.textContent = t || ''; h.hidden = !t; };

  // Один и тот же файл — один и тот же номер загрузки: оборвалось — продолжим с того же места.
  function nomerZagruzki(mid, f) {
    let h1 = 0x811c9dc5;
    let h2 = 0x01000193;
    for (const ch of `${mid}|${f.name}|${f.size}|${f.lastModified}`) {
      h1 = Math.imul(h1 ^ ch.charCodeAt(0), 16777619) >>> 0;
      h2 = Math.imul(h2 + ch.charCodeAt(0), 2654435761) >>> 0;
    }
    return 'z' + h1.toString(16).padStart(8, '0') + h2.toString(16).padStart(8, '0') + f.size.toString(16);
  }

  const mb = (n) => (n / 1048576).toFixed(n < 10485760 ? 1 : 0).replace('.', ',');
  const minuty = (sek) => (sek < 90 ? 'меньше двух минут' : `около ${Math.round(sek / 60)} мин`);

  function kusok(url, telo, nachalo, vsego, t0, imya) {
    return new Promise((ok, net) => {
      const x = new XMLHttpRequest();
      x.open('PUT', url);
      x.setRequestHeader('content-type', 'application/octet-stream');
      x.upload.onprogress = (e) => {
        const sdelano = nachalo + e.loaded;
        const skorost = sdelano > nachalo ? (sdelano - t0.s) / ((performance.now() - t0.t) / 1000) : 0;
        const ostalos = skorost > 0 ? (vsego - sdelano) / skorost : 0;
        hod(`Загружаю «${imya}»: ${mb(sdelano)} из ${mb(vsego)} МБ${ostalos > 5 ? `, осталось ${minuty(ostalos)}` : ''}. Страницу не закрывайте.`);
      };
      x.onload = () => {
        let d = null;
        try { d = JSON.parse(x.responseText); } catch { /* пусто */ }
        ok({ status: x.status, d });
      };
      x.onerror = () => net(new Error('связь'));
      x.ontimeout = () => net(new Error('связь'));
      x.send(telo);
    });
  }

  async function naServer(mid, f) {
    const token = nomerZagruzki(mid, f);
    const SHAG = 8 * 1024 * 1024;
    let at = 0;
    const t0 = { t: performance.now(), s: 0 };
    let sboi = 0;
    while (at < f.size) {
      const url = `api/arhiv/${encodeURIComponent(mid)}/${token}?offset=${at}`;
      let r;
      try {
        r = await kusok(url, f.slice(at, at + SHAG), at, f.size, t0, f.name);
      } catch {
        if (++sboi > 20) throw new Error('Связь пропала. Приложите файл ещё раз — загрузка продолжится с того же места.');
        hod(`Связь прервалась, пробую снова (${sboi})…`);
        await new Promise((z) => setTimeout(z, Math.min(30000, 2000 * sboi)));
        continue;
      }
      if (r.status === 409 && Number.isInteger(r.d?.have)) {
        // На сервере уже есть начало файла — продолжаем с него
        at = r.d.have;
        if (!t0.s) { t0.s = at; t0.t = performance.now(); }
        continue;
      }
      if (r.status !== 200) throw new Error(r.d?.error || 'Файл не загрузился.');
      at = r.d.have;
      sboi = 0;
    }
    hod(`Разбираю «${f.name}»: видео может занять несколько минут…`);
    const r = await fetch(`api/arhiv/${encodeURIComponent(mid)}/${token}/razobrat?name=${encodeURIComponent(f.name)}`, { method: 'POST' });
    const d = await r.json().catch(() => null);
    if (!r.ok) throw new Error(d?.error || 'Файл не разобрался.');
    return d;
  }

  let gruzim = false;

  async function prilozhit(fayly) {
    pokazatOshibku('');
    gruzim = true;
    knopka.disabled = true;
    let zametka = '';
    const propusheno = [];
    let dobavleno = 0;
    try {
      const mid = await gotovaModel();
      for (const f of fayly) {
        if (prostoeFoto(f)) {
          hod(`Загружаю «${f.name}»…`);
          const z = await (await fetch(`api/models/${encodeURIComponent(mid)}`, { cache: 'no-store' })).json();
          const n = Math.max(-1, ...(z.source?.photos || []).map((x) => x.n)) + 1;
          const s = await szhat(f);
          const r = await fetch(`api/photos/${encodeURIComponent(mid)}/${n}?view=${encodeURIComponent('из чата')}`, { method: 'PUT', headers: { 'content-type': s.type }, body: s.blob });
          if (!r.ok) throw new Error((await r.json().catch(() => null))?.error || 'Фото не загрузилось.');
          const m = await fetch(`api/models/${encodeURIComponent(mid)}/materialy`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ photos: [{ n }] }) });
          const zapis = await m.json();
          if (!m.ok) throw new Error(zapis.error);
          pokazatIstochniki(zapis);
          prilozheno.push({ podpis: `Фото «${f.name}»`, puti: [zapis.source.photos.at(-1).file], opis: `фото «${f.name}» — ${zapis.source.photos.at(-1).file}` });
          dobavleno += 1;
        } else {
          const d = await naServer(mid, f);
          pokazatIstochniki(d.zapis);
          propusheno.push(...d.skipped);
          if (d.photos.length) {
            const nomera = d.photos.map((x) => x.n);
            const papka = `foto/${mid}/`;
            const kadry = d.photos.filter((x) => /кадр \d+$/.test(x.view)).length;
            const sut = [d.photos.length - kadry ? chislo(d.photos.length - kadry, 'снимок', 'снимка', 'снимков') : '', kadry ? chislo(kadry, 'кадр', 'кадра', 'кадров') + ' из видео' : ''].filter(Boolean).join(' и ');
            prilozheno.push({
              podpis: `«${f.name}»: ${sut}`,
              puti: d.photos.map((x) => x.file),
              opis: `«${f.name}» — ${sut}: ${papka}${Math.min(...nomera)}.jpg … ${Math.max(...nomera)}.jpg (подпись каждого — в ${papka}<номер>.json)`,
            });
            dobavleno += d.photos.length;
          }
        }
        narisovatPrilozheno();
      }
      if (propusheno.length) zametka = (`Приложено: ${dobavleno}. Пропущено: ${propusheno.slice(0, 5).join(', ')}${propusheno.length > 5 ? ` и ещё ${propusheno.length - 5}` : ''}.`);
      else if (!dobavleno) zametka = 'В этом файле не нашлось ни снимков, ни видео.';
    } catch (e) {
      pokazatOshibku(dobavleno ? `Приложено ${dobavleno}, дальше не вышло: ${e.message}` : e.message);
    } finally {
      hod('');
      knopka.disabled = false;
      gruzim = false;
    }
    // Материалы — сразу в работу: с тем, что написано в поле, или с задачей по умолчанию.
    if (prilozheno.length) await otpravit();
    if (zametka) pokazatOshibku(zametka);
  }

  async function otpravit() {
    // Пока грузится файл, сообщение ждёт его и уйдёт вместе с ним
    if (gruzim) { soobshchit('Сообщение уйдёт вместе с файлом, когда он загрузится.'); return; }
    let t = tekst.value.trim();
    if (!t && prilozheno.length) t = 'Сделай модель по приложенным материалам.';
    if (!t) return;
    knopka.disabled = true;
    pokazatOshibku('');
    try {
      const mid = await gotovaModel();
      if (mid !== id) await pokazat(mid);
      const r0 = await fetch(`api/chat/${encodeURIComponent(mid)}/start`, { method: 'POST' });
      const d0 = await r0.json();
      if (!r0.ok) throw new Error(d0.error);
      conv = d0.conv;
      if (prilozheno.length) t += '\n\nПриложено (справочный материал): ' + prilozheno.map((f) => f.opis).join('; ');
      if (d0.first) t = `Модель: ${mid}, файл modeli/${mid}.json.\n\n${t}`;
      const forma = new URLSearchParams({ text: t, csrf: sost.csrf });
      const r = await fetch(adres('/send'), { method: 'POST', credentials: 'same-origin', body: forma });
      const d = await r.json();
      if (!r.ok) throw new Error(d.error || 'Не отправилось.');
      tekst.value = '';
      prilozheno = [];
      narisovatPrilozheno();
      await obnovit();
      vniz();
      slushat();
    } catch (e) {
      pokazatOshibku(e.message || 'Не отправилось — проверьте связь.');
      soobshchit(e.message || 'Не отправилось.', true);
    } finally {
      knopka.disabled = false;
      tekst.focus();
    }
  }

  $('#chat-forma').addEventListener('submit', (e) => { e.preventDefault(); otpravit(); });
  tekst.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey) && !e.isComposing) { e.preventDefault(); otpravit(); }
  });
  $('#f-chat').addEventListener('change', (e) => {
    const fayly = [...e.target.files];
    e.target.value = '';
    if (fayly.length) prilozhit(fayly);
  });
  lenta.addEventListener('click', (e) => {
    if (e.target.closest('#more-link')) {
      e.preventDefault();
      skolko += 40;
      obnovit().catch(() => {});
    }
  });

  return { pokazat };
}
