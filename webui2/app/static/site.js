// Замок и соседние вкладки
(function () {
  "use strict";
  var site = window.SITE || {};
  var key = "v2-state";
  var mine = site.locked ? "locked" : "open";

  // Сообщаем соседним вкладкам своё состояние
  try { localStorage.setItem(key, mine + ":" + Date.now()); } catch (e) { /* без хранилища — только сверка с сервером */ }

  function check() {
    fetch(site.root + "/state", {credentials: "same-origin", cache: "no-store"})
      .then(function (r) { return r.json(); })
      .then(function (s) {
        var now = !s.in ? "out" : (s.locked ? "locked" : "open");
        if (now !== mine) location.reload();
      })
      .catch(function () { /* сайт недоступен — оставляем как есть */ });
  }

  window.addEventListener("storage", function (e) {
    if (e.key === key && e.newValue && e.newValue.split(":")[0] !== mine) check();
  });
  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "visible") check();
  });

  var btn = document.getElementById("lock-btn");
  if (btn) {
    btn.addEventListener("click", function () {
      btn.disabled = true;
      fetch(site.root + "/lock", {
        method: "POST",
        credentials: "same-origin",
        headers: {"Content-Type": "application/x-www-form-urlencoded"},
        body: "csrf=" + encodeURIComponent(site.csrf)
      }).then(function () {
        try { localStorage.setItem(key, "locked:" + Date.now()); } catch (e) { /* ничего */ }
        location.reload();
      }).catch(function () { btn.disabled = false; });
    });
  }
})();
