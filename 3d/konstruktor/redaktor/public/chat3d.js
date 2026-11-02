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

  async function naServer(mid, f) {
    const token = Array.from(crypto.getRandomValues(new Uint8Array(12)), (x) => x.toString(16).padStart(2, '0')).join('');
    const SHAG = 16 * 1024 * 1024;
    for (let at = 0; at < f.size; at += SHAG) {
      hod(`Загружаю «${f.name}»: ${Math.round((at / f.size) * 100)}%`);
      const r = await fetch(`api/arhiv/${encodeURIComponent(mid)}/${token}?offset=${at}`, { method: 'PUT', headers: { 'content-type': 'application/octet-stream' }, body: f.slice(at, at + SHAG) });
      if (!r.ok) throw new Error((await r.json().catch(() => null))?.error || 'Файл не загрузился.');
    }
    hod(`Разбираю «${f.name}»: видео может занять несколько минут…`);
    const r = await fetch(`api/arhiv/${encodeURIComponent(mid)}/${token}/razobrat?name=${encodeURIComponent(f.name)}`, { method: 'POST' });
    const d = await r.json().catch(() => null);
    if (!r.ok) throw new Error(d?.error || 'Файл не разобрался.');
    return d;
  }

  async function prilozhit(fayly) {
    pokazatOshibku('');
    knopka.disabled = true;
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
      if (propusheno.length) pokazatOshibku(`Приложено: ${dobavleno}. Пропущено: ${propusheno.slice(0, 5).join(', ')}${propusheno.length > 5 ? ` и ещё ${propusheno.length - 5}` : ''}.`);
      else if (!dobavleno) pokazatOshibku('В этом файле не нашлось ни снимков, ни видео.');
      else soobshchit(`Приложено: ${dobavleno}.`);
    } catch (e) {
      pokazatOshibku(dobavleno ? `Приложено ${dobavleno}, дальше не вышло: ${e.message}` : e.message);
    } finally {
      hod('');
      knopka.disabled = false;
    }
  }

  async function otpravit() {
    let t = tekst.value.trim();
    if (!t && prilozheno.length) t = 'Учти приложенные материалы.';
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
