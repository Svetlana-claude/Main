// Распаковка ZIP с фотографиями прямо в браузере: на сервер уходят уже сжатые снимки.

const KARTINKI = /\.(jpe?g|png|webp|gif|bmp|avif)$/i;
const MAX_ARHIV = 1024 * 1024 * 1024;    // сам архив
const MAX_FOTO = 80 * 1024 * 1024;       // один снимок в распакованном виде
const MAX_VSEGO = 2 * 1024 * 1024 * 1024; // всё вместе: защита от архива-бомбы

// Русские имена: новые архиваторы пишут UTF-8, старые на Windows — кодировку cp866.
function imyaIz(bajty, utf8) {
  try {
    return new TextDecoder('utf-8', { fatal: !utf8 }).decode(bajty);
  } catch {
    return new TextDecoder('ibm866').decode(bajty);
  }
}

async function raspakovat(szhatye, metod, razmer) {
  if (metod === 0) return szhatye;
  // Читаем с пределом: заголовку архива о размере верить нельзя.
  const potok = szhatye.stream().pipeThrough(new DecompressionStream('deflate-raw'));
  const chitatel = potok.getReader();
  const kuski = [];
  let vsego = 0;
  for (;;) {
    const { done, value } = await chitatel.read();
    if (done) break;
    vsego += value.length;
    if (vsego > Math.min(razmer, MAX_FOTO)) { await chitatel.cancel(); throw new Error('слишком большой файл'); }
    kuski.push(value);
  }
  return new Blob(kuski);
}

// Возвращает { foto: [{ fayl, imya, vid }], propusheno: [имена] }.
export async function fotoIzZip(arhiv) {
  if (arhiv.size > MAX_ARHIV) throw new Error('Архив больше 1 ГБ — разбейте его на части.');
  const hvost = new DataView(await arhiv.slice(Math.max(0, arhiv.size - 66000)).arrayBuffer());
  let eocd = -1;
  for (let i = hvost.byteLength - 22; i >= 0; i--) {
    if (hvost.getUint32(i, true) === 0x06054b50) { eocd = i; break; }
  }
  if (eocd < 0) throw new Error(`«${arhiv.name}» не похож на архив ZIP.`);
  const chislo = hvost.getUint16(eocd + 10, true);
  const dlinaKataloga = hvost.getUint32(eocd + 12, true);
  const smeshchenie = hvost.getUint32(eocd + 16, true);
  if (chislo === 0xffff || smeshchenie === 0xffffffff) throw new Error('Архив слишком большой для чтения здесь: разбейте его на части.');
  const katalog = new DataView(await arhiv.slice(smeshchenie, smeshchenie + dlinaKataloga).arrayBuffer());

  const zapisi = [];
  const propusheno = [];
  for (let p = 0, i = 0; i < chislo; i++) {
    if (p + 46 > katalog.byteLength || katalog.getUint32(p, true) !== 0x02014b50) throw new Error('Архив повреждён.');
    const flagi = katalog.getUint16(p + 8, true);
    const metod = katalog.getUint16(p + 10, true);
    const szhato = katalog.getUint32(p + 20, true);
    const razmer = katalog.getUint32(p + 24, true);
    const dlIm = katalog.getUint16(p + 28, true);
    const dlDop = katalog.getUint16(p + 30, true);
    const dlKom = katalog.getUint16(p + 32, true);
    const smesh = katalog.getUint32(p + 42, true);
    const put = imyaIz(new Uint8Array(katalog.buffer, katalog.byteOffset + p + 46, dlIm), !!(flagi & 0x800));
    p += 46 + dlIm + dlDop + dlKom;
    const imya = put.split(/[\\/]/).pop();
    // Папки и служебное macOS — не считаем за пропуск
    if (!imya || put.startsWith('__MACOSX/') || imya.startsWith('.')) continue;
    if (!KARTINKI.test(imya)) { propusheno.push(imya); continue; }
    if (flagi & 1) throw new Error('Архив с паролем: снимите пароль и загрузите снова.');
    if ((metod !== 0 && metod !== 8) || razmer > MAX_FOTO) { propusheno.push(imya); continue; }
    zapisi.push({ imya, metod, szhato, razmer, smesh });
  }
  zapisi.sort((a, b) => a.imya.localeCompare(b.imya, 'ru', { numeric: true }));

  const foto = [];
  let vsego = 0;
  for (const z of zapisi) {
    vsego += z.razmer;
    if (vsego > MAX_VSEGO) throw new Error('В архиве слишком много данных: разбейте его на части.');
    try {
      const shapka = new DataView(await arhiv.slice(z.smesh, z.smesh + 30).arrayBuffer());
      if (shapka.getUint32(0, true) !== 0x04034b50) throw new Error('повреждён');
      const nachalo = z.smesh + 30 + shapka.getUint16(26, true) + shapka.getUint16(28, true);
      const bajty = await raspakovat(arhiv.slice(nachalo, nachalo + z.szhato), z.metod, z.razmer);
      foto.push({ fayl: new File([bajty], z.imya), imya: z.imya, vid: z.imya.replace(/\.[^.]+$/, '').slice(0, 40) });
    } catch { propusheno.push(z.imya); }
  }
  return { foto, propusheno };
}
