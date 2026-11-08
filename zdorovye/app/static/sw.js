// Работник «Здоровья»: только чтобы сайт ставился как приложение.
// Ничего не кэширует — данные о здоровье не должны оседать на телефоне.
self.addEventListener("install", function () { self.skipWaiting(); });
self.addEventListener("activate", function (e) { e.waitUntil(self.clients.claim()); });
self.addEventListener("fetch", function (e) {
  if (e.request.mode !== "navigate") return;
  e.respondWith(fetch(e.request).catch(function () {
    return new Response(
      '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">' +
      '<title>Нет связи</title><body style="font:16px system-ui;padding:2rem;text-align:center">' +
      '<h1>Нет связи</h1><p>Проверь интернет и обнови страницу.</p></body>',
      { headers: { "Content-Type": "text/html; charset=utf-8" } });
  }));
});
