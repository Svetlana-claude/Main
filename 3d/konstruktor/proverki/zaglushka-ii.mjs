// Заглушка ИИ для проверок: отвечает как настоящий сервис, но без затрат.
// Запросы пишет в /tmp/zaglushka-ii.log, чтобы проверить, что ушло.
import http from 'node:http';
import { readFileSync, appendFileSync } from 'node:fs';
const obrazec = JSON.parse(readFileSync(new URL('../redaktor/public/modeli/parashyut.json', import.meta.url)));
let n = 0;
http.createServer((req, res) => {
  const kuski = [];
  req.on('data', (c) => kuski.push(c));
  req.on('end', () => {
    const telo = Buffer.concat(kuski);
    appendFileSync('/tmp/zaglushka-ii.log', JSON.stringify({ url: req.url, key: req.headers['x-api-key'] || req.headers['authorization'] || null, beta: req.headers['anthropic-beta'] || null, zag: Object.keys(req.headers).join(','), dlina: telo.length, nachalo: (req.url.startsWith('/v1/files') ? telo.slice(0, 300) : telo).toString('utf8') }) + '\n');
    res.setHeader('content-type', 'application/json');
    if (req.url.startsWith('/v1/files')) {
      n++;
      res.end(JSON.stringify({ id: 'file_test_' + n, type: 'file', filename: 'foto.jpg', mime_type: 'image/jpeg', size_bytes: telo.length, created_at: new Date().toISOString(), downloadable: false }));
      return;
    }
    const zapros = JSON.parse(telo.toString('utf8'));
    const tekstZaprosa = JSON.stringify(zapros.messages);
    const m = structuredClone(obrazec);
    if (tekstZaprosa.includes('Просьба:')) {
      m.name = 'Парашют (поправлено)';
      m.parts.find((p) => p.id === 'kupol').position[1] = 7.2;
    } else m.name = 'Парашют по фото';
    res.end(JSON.stringify({ id: 'msg_test', type: 'message', role: 'assistant', model: zapros.model, content: [{ type: 'text', text: JSON.stringify(m) }], stop_reason: 'end_turn', stop_sequence: null, usage: { input_tokens: 10, output_tokens: 10 } }));
  });
}).listen(8799, '127.0.0.1');
