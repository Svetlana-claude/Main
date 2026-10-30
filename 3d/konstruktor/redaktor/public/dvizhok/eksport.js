// Сборка автономного просмотрщика одной модели в один HTML-файл.
// Им же пользуется «Предпросмотр как на сайте» — поэтому они совпадают.
// В файл попадают только библиотека показа, движок и одна модель:
// ни редактора, ни загрузки фото, ни обращений к серверу.

// Текст внутри <script> не должен закрывать тег раньше времени.
const bezopasno = (s) => s.replace(/<\/script/gi, '<\\/script').replace(/<!--/g, '<\\!--');
const ekranHtml = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

export function sobratStranicu({ model, three, format, dvizhok }) {
  const json = JSON.stringify(model).replace(/</g, '\\u003c');
  return `<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${ekranHtml(model.name)}</title>
<meta name="robots" content="noindex">
<link rel="icon" href="data:,">
<style>html,body{margin:0;height:100%;background:#f4f6f8}#prosmotr{height:100%}
#oshibka{display:none;padding:24px;font:15px system-ui,sans-serif;color:#7a2a1a}</style>
</head>
<body>
<div id="prosmotr"></div>
<div id="oshibka">Не удалось показать модель: браузер не поддерживает 3D (WebGL).</div>
<script type="application/json" id="dv-model">${json}</script>
<script type="text/plain" id="dv-three">${bezopasno(three)}</script>
<script type="text/plain" id="dv-format">${bezopasno(format)}</script>
<script type="text/plain" id="dv-dvizhok">${bezopasno(dvizhok)}</script>
<script type="module">
const tekst = (id) => document.getElementById(id).textContent;
const adres = (s) => URL.createObjectURL(new Blob([s], { type: 'text/javascript' }));
try {
  const three = adres(tekst('dv-three'));
  const format = adres(tekst('dv-format'));
  const dvizhok = adres(tekst('dv-dvizhok')
    .replace(/from\\s*['"]three['"]/g, "from '" + three + "'")
    .replace(/from\\s*['"]\\.\\/format\\.js['"]/g, "from '" + format + "'"));
  const { sozdatProsmotr } = await import(dvizhok);
  window.prosmotr = sozdatProsmotr(document.getElementById('prosmotr'), JSON.parse(tekst('dv-model')));
} catch (e) {
  console.error(e);
  document.getElementById('oshibka').style.display = 'block';
}
</script>
</body>
</html>
`;
}

// В браузере: подтянуть исходники с того же сайта и собрать страницу.
export async function sobratVBrauzere(model, baza = new URL('..', import.meta.url).href) {
  const vzyat = async (put) => {
    const r = await fetch(new URL(put, baza));
    if (!r.ok) throw new Error(`Не загрузился ${put}`);
    return r.text();
  };
  const [three, format, dvizhok] = await Promise.all([
    vzyat('vendor/three-bundle.min.js'),
    vzyat('dvizhok/format.js'),
    vzyat('dvizhok/dvizhok.js'),
  ]);
  return sobratStranicu({ model, three, format, dvizhok });
}
