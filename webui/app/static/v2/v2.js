// Рабочее место v2: лента, отправка, поток ответа, «Стоп». Без библиотек.
'use strict';

// ---------- Markdown: только то, что реально пишет Claude ----------

function escapeHtml(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function inline(s) {
  // Код в обратных кавычках прячется, чтобы внутри не сработали прочие замены
  const codes = [];
  s = s.replace(/`([^`]+)`/g, (_, c) => { codes.push(c); return '\u0000' + (codes.length - 1) + '\u0000'; });
  s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
       .replace(/(^|[^*])\*([^*\s][^*]*)\*/g, '$1<em>$2</em>')
       .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+|\/[^)\s]*)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  return s.replace(/\u0000(\d+)\u0000/g, (_, i) => '<code>' + codes[i] + '</code>');
}

function renderMarkdown(src) {
  const lines = escapeHtml(src).split('\n');
  const out = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (/^```/.test(line)) {                       // блок кода
      const body = [];
      for (i++; i < lines.length && !/^```/.test(lines[i]); i++) body.push(lines[i]);
      out.push('<pre><code>' + body.join('\n') + '</code></pre>');
      i++;
    } else if (/^#{1,6} /.test(line)) {           // заголовок
      const level = Math.min(line.match(/^#+/)[0].length + 1, 6);
      out.push(`<h${level}>${inline(line.replace(/^#+ /, ''))}</h${level}>`);
      i++;
    } else if (/^\s*\|.*\|\s*$/.test(line)) {     // таблица
      const rows = [];
      for (; i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i]); i++) {
        if (/^\s*\|[\s:|-]+\|\s*$/.test(lines[i])) continue;
        const cells = lines[i].trim().slice(1, -1).split('|').map(c => inline(c.trim()));
        const tag = rows.length ? 'td' : 'th';
        rows.push('<tr>' + cells.map(c => `<${tag}>${c}</${tag}>`).join('') + '</tr>');
      }
      out.push('<table>' + rows.join('') + '</table>');
    } else if (/^\s*([-*]|\d+\.) /.test(line)) {  // список
      const ordered = /^\s*\d+\./.test(line);
      const items = [];
      for (; i < lines.length && /^\s*([-*]|\d+\.) /.test(lines[i]); i++) {
        items.push('<li>' + inline(lines[i].replace(/^\s*([-*]|\d+\.) /, '')) + '</li>');
      }
      out.push((ordered ? '<ol>' : '<ul>') + items.join('') + (ordered ? '</ol>' : '</ul>'));
    } else if (line.trim() === '') {
      i++;
    } else {                                       // абзац
      const para = [];
      for (; i < lines.length && lines[i].trim() !== '' &&
             !/^(```|#{1,6} |\s*([-*]|\d+\.) |\s*\|)/.test(lines[i]); i++) para.push(inline(lines[i]));
      out.push('<p>' + para.join('<br>') + '</p>');
    }
  }
  return out.join('');
}

function paint(el, text) {
  el.innerHTML = renderMarkdown(text);
  el.classList.add('is-rendered');
}

// ---------- Лента ----------

const app = document.getElementById('app');
const feed = document.getElementById('feed');
const form = document.getElementById('composer');

document.querySelectorAll('.feed .md').forEach(el => paint(el, el.textContent));

function nearBottom() { return feed.scrollHeight - feed.scrollTop - feed.clientHeight < 80; }
function toBottom() { feed.scrollTop = feed.scrollHeight; }
toBottom();

function addMessage(role, text) {
  const msg = document.createElement('div');
  msg.className = 'msg msg-' + role;
  const md = document.createElement('div');
  md.className = 'md';
  md.textContent = text;
  msg.appendChild(md);
  feed.appendChild(msg);
  return md;
}

// ---------- Боковой список на телефоне ----------

const toggle = document.getElementById('side-toggle');
toggle.addEventListener('click', () => {
  const open = app.classList.toggle('side-open');
  toggle.setAttribute('aria-expanded', open);
});
app.addEventListener('click', e => {
  if (app.classList.contains('side-open') && !e.target.closest('.side') && e.target !== toggle) {
    app.classList.remove('side-open');
    toggle.setAttribute('aria-expanded', 'false');
  }
});

// ---------- Отправка и поток ----------

if (form) {
  const textarea = document.getElementById('text');
  const sendBtn = document.getElementById('send');
  const stopBtn = document.getElementById('stop');
  const touch = matchMedia('(pointer: coarse)').matches;

  const grow = () => { textarea.style.height = 'auto'; textarea.style.height = textarea.scrollHeight + 'px'; };
  textarea.addEventListener('input', grow);

  // На компьютере Enter — отправить, Shift+Enter — новая строка.
  // На телефоне Enter — новая строка, отправка — кнопкой.
  textarea.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey && !touch && !e.isComposing) {
      e.preventDefault();
      form.requestSubmit();
    }
  });

  function busy(on) {
    sendBtn.disabled = on;
    stopBtn.hidden = !on;
  }

  function follow(onlyActive) {
    busy(true);
    const live = addMessage('wait', 'Думаю…');
    let text = '';      // весь показанный ответ
    let block = '';     // текст текущего блока, пришедший кусочками
    let started = false;
    let finished = false;
    const url = form.dataset.stream + '?start=0' + (onlyActive ? '&active=1' : '');
    const es = new EventSource(url);

    const show = () => {
      const stick = nearBottom();
      if (!started) { started = true; live.parentNode.className = 'msg msg-assistant'; }
      live.textContent = text;
      if (stick) toBottom();
    };
    const finish = () => {
      if (finished) return;
      finished = true;
      es.close();
      if (!started) live.parentNode.remove();
      else paint(live, text);
      busy(false);
    };

    es.onmessage = e => {
      const ev = JSON.parse(e.data);
      switch (ev.type) {
        case 'delta': block += ev.text; text += ev.text; show(); break;
        case 'text':
          if (!block) { text += (text ? '\n\n' : '') + ev.text; show(); }
          else text += '\n\n';
          block = '';
          break;
        case 'result':
          if (ev.text) text = ev.text;
          if (ev.is_error) live.parentNode.className = 'msg msg-error';
          started = true; show();
          break;
        case 'error':
          addMessage('error', ev.message);
          break;
        case 'title':
          document.querySelector('.head-title').textContent = ev.title;
          document.title = ev.title;
          break;
        case 'done': finish(); break;
        // init, tool, usage, compact — ход работы скрыт
      }
    };
    es.onerror = () => {
      if (!finished) { addMessage('error', 'Связь с сервером прервалась — обновите страницу'); finish(); }
    };
  }

  form.addEventListener('submit', async e => {
    e.preventDefault();
    const value = textarea.value.trim();
    if (!value || sendBtn.disabled) return;
    busy(true);
    const resp = await fetch(form.dataset.send, { method: 'POST', body: new URLSearchParams({ text: value }) })
      .catch(() => null);
    if (!resp || !resp.ok) {
      const err = resp ? (await resp.json().catch(() => ({}))).error : 'нет связи';
      addMessage('error', 'Не отправлено: ' + (err || resp.status));
      busy(false);
      return;
    }
    paint(addMessage('user', value), value);
    textarea.value = '';
    grow();
    toBottom();
    follow(false);
  });

  stopBtn.addEventListener('click', () => fetch(form.dataset.stop, { method: 'POST' }));

  if (form.dataset.running === '1') follow(true);
}
