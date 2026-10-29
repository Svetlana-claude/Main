// Безопасность: проверка по кнопке и «так и должно быть» — ждём конца и обновляем страницу
(function () {
  "use strict";
  var site = window.SITE || {};
  var box = document.getElementById("sec");
  var msg = document.getElementById("sec-msg");
  if (!box) return;
  var buttons = box.querySelectorAll("[data-sec]");
  var timer = null;

  function lock(on) { buttons.forEach(function (b) { b.disabled = on; }); }
  function say(text, error) {
    msg.textContent = text;
    msg.className = error ? "error" : "status-line";
    msg.hidden = !text;
  }

  function show(s) {
    if (s.what) {
      lock(true);
      say(s.what === "approve" ? "Принимаю как норму и проверяю заново…" : "Проверяю сервер…");
      if (!timer) timer = setInterval(poll, 2000);
      return;
    }
    if (timer) { clearInterval(timer); timer = null; }
    if (s.error) { lock(false); say(s.error, true); return; }
    location.reload();
  }

  function poll() {
    fetch(site.root + "/security/state", {credentials: "same-origin", cache: "no-store"})
      .then(function (r) { if (!r.ok) throw new Error("нет ответа"); return r.json(); })
      .then(show)
      .catch(function () { /* сайт на миг недоступен — спросим ещё раз */ });
  }

  buttons.forEach(function (b) {
    b.addEventListener("click", function () {
      if (!confirm(b.dataset.ask)) return;
      lock(true);
      fetch(site.root + "/security/" + b.dataset.sec, {
        method: "POST", credentials: "same-origin",
        headers: {"Content-Type": "application/x-www-form-urlencoded"},
        body: "csrf=" + encodeURIComponent(site.csrf)
      }).then(function (r) { return r.json(); })
        .then(function (s) {
          if (s.error && !s.what) { say(s.error, true); lock(false); return; }
          show(s);
        })
        .catch(function () { say("Не получилось — обнови страницу", true); lock(false); });
    });
  });
  if (box.dataset.what) { lock(true); timer = setInterval(poll, 2000); }
})();
