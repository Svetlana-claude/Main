// Окно разговора с Claude рядом с моделью. У каждой модели своя тема в проекте
// «3D-модели»; лента, отправка и поток ответа — те же адреса, что у тем на сайте.

const $ = (s) => document.querySelector(s);

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
    for (const f of prilozheno) {
      const img = document.createElement('img');
      img.src = f.prevyu;
      img.alt = f.put;
      box.append(img);
    }
  }

  async function prilozhit(fayly) {
    pokazatOshibku('');
    try {
      const mid = await gotovaModel();
      const z = await (await fetch(`api/models/${encodeURIComponent(mid)}`, { cache: 'no-store' })).json();
      let n = Math.max(-1, ...(z.source?.photos || []).map((f) => f.n)) + 1;
      for (const f of fayly) {
        const s = await szhat(f);
        const r = await fetch(`api/photos/${encodeURIComponent(mid)}/${n}?view=${encodeURIComponent('из чата')}`, { method: 'PUT', headers: { 'content-type': s.type }, body: s.blob });
        if (!r.ok) throw new Error((await r.json().catch(() => null))?.error || 'Фото не загрузилось.');
        const m = await fetch(`api/models/${encodeURIComponent(mid)}/materialy`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ photos: [{ n }] }) });
        const zapis = await m.json();
        if (!m.ok) throw new Error(zapis.error);
        pokazatIstochniki(zapis);
        prilozheno.push({ put: zapis.source.photos.at(-1).file, prevyu: s.prevyu });
        n += 1;
      }
      narisovatPrilozheno();
    } catch (e) { pokazatOshibku(e.message); }
  }

  async function otpravit() {
    let t = tekst.value.trim();
    if (!t && prilozheno.length) t = 'Посмотри приложенные фото.';
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
      if (prilozheno.length) t += '\n\nПриложено: ' + prilozheno.map((f) => f.put).join(', ');
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
