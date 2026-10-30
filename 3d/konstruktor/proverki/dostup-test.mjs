// Проверка пропуска Access: свои ключи подписи, поддельный ответ сервиса ключей.
import { proveritVhod } from '../redaktor/src/dostup.js';

const KOMANDA = 'proverka.cloudflareaccess.com';
const AUD = 'aud-test-123';
const para = await crypto.subtle.generateKey({ name: 'RSASSA-PKCS1-v1_5', modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: 'SHA-256' }, true, ['sign', 'verify']);
const chuzhaya = await crypto.subtle.generateKey({ name: 'RSASSA-PKCS1-v1_5', modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: 'SHA-256' }, true, ['sign', 'verify']);
const jwk = { ...(await crypto.subtle.exportKey('jwk', para.publicKey)), kid: 'k1', alg: 'RS256' };
globalThis.fetch = async (url) => {
  if (String(url) === `https://${KOMANDA}/cdn-cgi/access/certs`) return new Response(JSON.stringify({ keys: [jwk] }));
  throw new Error('неожиданный запрос ' + url);
};
const b64 = (o) => Buffer.from(typeof o === 'string' ? o : JSON.stringify(o)).toString('base64url');
async function token(dannye, klyuch = para.privateKey, kid = 'k1') {
  const nachalo = b64({ alg: 'RS256', kid }) + '.' + b64(dannye);
  const podpis = await crypto.subtle.sign('RSASSA-PKCS1-v1_5', klyuch, new TextEncoder().encode(nachalo));
  return nachalo + '.' + Buffer.from(podpis).toString('base64url');
}
const seychas = Math.floor(Date.now() / 1000);
const horoshie = { aud: [AUD], iss: `https://${KOMANDA}`, exp: seychas + 600, iat: seychas, email: 'svetlana@example.com' };
const env = { ACCESS_TEAM_DOMAIN: KOMANDA, ACCESS_AUD: AUD };
const zapros = (zag = {}) => new Request('https://3d.mokeevasky.ru/api/status', { headers: zag });
const itog = [];
const ok = (u, t) => itog.push((u ? 'OK   ' : 'FAIL ') + t);

ok((await proveritVhod(zapros({ 'cf-access-jwt-assertion': await token(horoshie) }), env))?.email === 'svetlana@example.com', 'настоящий пропуск — пускает');
ok(await proveritVhod(zapros(), env) === null, 'без пропуска — не пускает');
ok(await proveritVhod(zapros({ 'cf-access-jwt-assertion': await token(horoshie, chuzhaya.privateKey) }), env) === null, 'пропуск с чужой подписью — не пускает');
ok(await proveritVhod(zapros({ 'cf-access-jwt-assertion': await token({ ...horoshie, aud: ['drugoe'] }) }), env) === null, 'пропуск от другого приложения — не пускает');
ok(await proveritVhod(zapros({ 'cf-access-jwt-assertion': await token({ ...horoshie, exp: seychas - 10 }) }), env) === null, 'просроченный пропуск — не пускает');
ok(await proveritVhod(zapros({ 'cf-access-jwt-assertion': await token({ ...horoshie, iss: 'https://chuzhaya.cloudflareaccess.com' }) }), env) === null, 'пропуск чужой команды — не пускает');
const t = await token(horoshie);
const [a, , c] = t.split('.');
ok(await proveritVhod(zapros({ 'cf-access-jwt-assertion': `${a}.${b64({ ...horoshie, email: 'vzlom@example.com' })}.${c}` }), env) === null, 'подменённая почта в пропуске — не пускает');
ok(await proveritVhod(zapros({ 'cf-access-jwt-assertion': t }), {}) === null, 'Access не настроен — не пускает никого');
ok(await proveritVhod(zapros({ 'cf-connecting-ip': '127.0.0.1' }), { LOCAL_DEV: '1' }) !== null, 'локальный запуск с этого компьютера — пускает');
ok(await proveritVhod(zapros({ 'cf-connecting-ip': '85.1.2.3' }), { LOCAL_DEV: '1' }) === null, 'признак локального запуска с чужого адреса — не пускает');
ok(await proveritVhod(zapros({ 'cf-connecting-ip': '127.0.0.1' }), env) === null, 'на сервере без признака локального запуска — 127.0.0.1 не помогает');
console.log(itog.join('\n'));
