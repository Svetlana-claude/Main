// Проверка входа через Cloudflare Access.
// Access сам не пускает посторонних на адрес редактора, а здесь — вторая
// линия: каждая страница и каждая серверная функция проверяет подписанный
// пропуск. Если пропуска нет или он чужой — отказ, даже если запрос пришёл
// в обход Access (например, по служебному адресу workers.dev).

let kesh = { klyuchi: null, vremya: 0 };

function izBase64Url(s) {
  const b = atob(s.replace(/-/g, '+').replace(/_/g, '/') + '==='.slice((s.length + 3) % 4));
  return Uint8Array.from(b, (c) => c.charCodeAt(0));
}

async function klyuchiAccess(komanda) {
  if (kesh.klyuchi && Date.now() - kesh.vremya < 60 * 60 * 1000) return kesh.klyuchi;
  const r = await fetch(`https://${komanda}/cdn-cgi/access/certs`);
  if (!r.ok) throw new Error('Не получены ключи Access');
  const { keys } = await r.json();
  kesh = { klyuchi: keys, vremya: Date.now() };
  return keys;
}

// Возвращает { email } или null.
export async function proveritVhod(request, env) {
  // Локальный запуск для разработки: признак задаётся только в .dev.vars (на сервер
  // не уходит), и запрос должен прийти с этого же компьютера. На настоящем адресе
  // Cloudflare сам ставит в cf-connecting-ip адрес посетителя — подделать его нельзя.
  const ip = request.headers.get('cf-connecting-ip');
  if (env.LOCAL_DEV === '1' && (ip === '127.0.0.1' || ip === '::1')) return { email: 'локальный запуск' };

  const komanda = env.ACCESS_TEAM_DOMAIN; // например, mokeeva.cloudflareaccess.com
  const aud = env.ACCESS_AUD;
  if (!komanda || !aud) return null; // не настроено — не пускаем никого
  const token = request.headers.get('cf-access-jwt-assertion');
  if (!token) return null;
  const chasti = token.split('.');
  if (chasti.length !== 3) return null;
  try {
    const shapka = JSON.parse(new TextDecoder().decode(izBase64Url(chasti[0])));
    const dannye = JSON.parse(new TextDecoder().decode(izBase64Url(chasti[1])));
    if (shapka.alg !== 'RS256') return null;
    const klyuch = (await klyuchiAccess(komanda)).find((k) => k.kid === shapka.kid);
    if (!klyuch) return null;
    const pub = await crypto.subtle.importKey('jwk', klyuch, { name: 'RSASSA-PKCS1-v1_5', hash: 'SHA-256' }, false, ['verify']);
    const verno = await crypto.subtle.verify('RSASSA-PKCS1-v1_5', pub, izBase64Url(chasti[2]), new TextEncoder().encode(chasti[0] + '.' + chasti[1]));
    if (!verno) return null;
    const seychas = Date.now() / 1000;
    const auds = Array.isArray(dannye.aud) ? dannye.aud : [dannye.aud];
    if (!auds.includes(aud)) return null;
    if (dannye.iss !== `https://${komanda}`) return null;
    if (!(dannye.exp > seychas) || (dannye.nbf && dannye.nbf > seychas + 60)) return null;
    return { email: dannye.email || '' };
  } catch {
    return null;
  }
}
