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

  // Кружки и щит сверяются с сайтом сами, пока страница на виду
  var TEXT = {free: "Свободен", busy: "Работает", wait: "Ждёт разрешения"};
  var badge = document.getElementById("ask-count");
  var perms = document.getElementById("perms");

  function paint(el, state) {
    if (el.classList.contains(state)) return;
    el.classList.remove("free", "busy", "wait");
    el.classList.add(state);
    el.title = TEXT[state];
    el.setAttribute("aria-label", TEXT[state]);
  }

  function lights() {
    if (!badge || document.visibilityState !== "visible") return;
    fetch(site.root + "/lights", {credentials: "same-origin", cache: "no-store"})
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (s) {
        if (!s) return;
        badge.textContent = s.ask;
        badge.hidden = !s.ask;
        // На странице «Разрешения» новый или снятый вопрос — сразу виден
        if (perms && String(s.ask) !== perms.dataset.asks) location.reload();
        document.querySelectorAll(".light[data-c]").forEach(function (el) {
          paint(el, s.c[el.dataset.c] || "free");
        });
        document.querySelectorAll(".light[data-p]").forEach(function (el) {
          paint(el, s.p[el.dataset.p] || "free");
        });
      })
      .catch(function () { /* сайт недоступен — оставляем как есть */ });
  }
  setInterval(lights, 3000);
  document.addEventListener("visibilitychange", lights);
})();
