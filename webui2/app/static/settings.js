// Настройки: перезапуск с ожиданием, замер нагрузки, подсказки на графиках
(function () {
  "use strict";
  var site = window.SITE || {};

  function post(path) {
    return fetch(site.root + path, {
      method: "POST", credentials: "same-origin",
      headers: {"Content-Type": "application/x-www-form-urlencoded"},
      body: "csrf=" + encodeURIComponent(site.csrf)
    }).then(function (r) { return r.json(); });
  }

  // ── Перезапуск ──────────────────────────────────────────────────────
  var box = document.getElementById("power");
  var msg = document.getElementById("power-msg");
  var cancelBtn = document.getElementById("power-cancel");
  var buttons = box ? box.querySelectorAll("[data-power]") : [];
  var boot = box ? box.dataset.boot : "";
  var timer = null;
  var gone = 0;

  function say(text, error) {
    msg.textContent = text;
    msg.className = error ? "error" : "status-line";
    msg.hidden = !text;
  }

  function lock(on) {
    buttons.forEach(function (b) { b.disabled = on; });
  }

  function show(s) {
    if (s.boot && s.boot !== boot) { location.reload(); return; }
    if (!s.what) {
      lock(false);
      cancelBtn.hidden = true;
      say(s.error || "", Boolean(s.error));
      stop();
      return;
    }
    lock(true);
    var name = s.what === "server" ? "сервер" : "сайт";
    if (s.phase === "waiting") {
      var left = [];
      if (s.runs) left.push("ответов: " + s.runs);
      if (s.deleting) left.push("удалений проекта: " + s.deleting);
      say("Жду, пока допишутся " + (left.join(", ") || "ответы") + ". Потом перезапущу " + name + ".");
      cancelBtn.hidden = false;
    } else {
      say(s.what === "server" ? "Перезагружаю сервер…" : "Перезапускаю сайт…");
      cancelBtn.hidden = true;
    }
  }

  function poll() {
    fetch(site.root + "/settings/power", {credentials: "same-origin", cache: "no-store"})
      .then(function (r) { if (!r.ok) throw new Error("нет ответа"); return r.json(); })
      .then(function (s) { gone = 0; show(s); })
      .catch(function () {
        // Сайт лёг — значит, перезапуск идёт; ждём, пока поднимется
        gone += 1;
        lock(true);
        cancelBtn.hidden = true;
        say(gone > 150 ? "Сайт долго не поднимается. Обнови страницу чуть позже."
                       : "Сайт перезапускается, страница обновится сама…");
      });
  }

  function watch() { if (!timer) timer = setInterval(poll, 2000); }
  function stop() { if (timer) { clearInterval(timer); timer = null; } }

  buttons.forEach(function (b) {
    b.addEventListener("click", function () {
      if (!confirm(b.dataset.ask)) return;
      lock(true);
      post("/settings/power/" + b.dataset.power)
        .then(function (s) { if (s.error && !s.what) { say(s.error, true); lock(false); return; } show(s); watch(); })
        .catch(function () { say("Не получилось — обнови страницу", true); lock(false); });
    });
  });
  if (cancelBtn) {
    cancelBtn.addEventListener("click", function () {
      post("/settings/power/cancel").then(show);
    });
  }
  if (box && box.dataset.what) { lock(true); poll(); watch(); }

  // ── Нагрузка сейчас ─────────────────────────────────────────────────
  var loadBtn = document.getElementById("load-btn");
  function put(id, value, note) {
    document.getElementById(id).textContent = Math.round(value) + " %";
    document.getElementById(id + "-note").textContent = note;
  }
  if (loadBtn) {
    loadBtn.addEventListener("click", function () {
      loadBtn.disabled = true;
      fetch(site.root + "/settings/load", {credentials: "same-origin", cache: "no-store"})
        .then(function (r) { return r.json(); })
        .then(function (s) {
          put("load-cpu", s.cpu, "сейчас, ядер: " + s.cores);
          put("load-mem", s.mem, s.mem_text);
          put("load-disk", s.disk, s.disk_text);
        })
        .catch(function () { /* сайт недоступен — оставляем прежние цифры */ })
        .then(function () { loadBtn.disabled = false; });
    });
  }

  // ── Подсказка на графике: ближайший замер под пальцем или мышью ─────
  document.querySelectorAll(".chart").forEach(function (fig) {
    var points = JSON.parse(fig.dataset.points || "[]");
    var svg = fig.querySelector("svg");
    var cross = fig.querySelector(".cross");
    var dot = fig.querySelector(".cross-dot");
    var tip = fig.querySelector(".tip");
    if (!points.length) return;

    function at(evt) {
      var rect = svg.getBoundingClientRect();
      var vb = svg.viewBox.baseVal;
      var x = (evt.clientX - rect.left) * vb.width / rect.width;
      var best = points[0];
      points.forEach(function (p) { if (Math.abs(p[0] - x) < Math.abs(best[0] - x)) best = p; });
      cross.setAttribute("x1", best[0]); cross.setAttribute("x2", best[0]);
      dot.setAttribute("cx", best[0]); dot.setAttribute("cy", best[1]);
      cross.setAttribute("visibility", "visible"); dot.setAttribute("visibility", "visible");
      tip.textContent = best[3] + " — " + best[2];
      tip.hidden = false;
      var left = best[0] * rect.width / vb.width;
      tip.style.left = Math.min(Math.max(left, 40), rect.width - 40) + "px";
    }
    function off() {
      cross.setAttribute("visibility", "hidden"); dot.setAttribute("visibility", "hidden");
      tip.hidden = true;
    }
    svg.addEventListener("pointermove", at);
    svg.addEventListener("pointerdown", at);
    svg.addEventListener("pointerleave", off);
  });
})();
