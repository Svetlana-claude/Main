// Здоровье: подтверждения, копирование ссылки, автообновление, установка как приложение.
(function () {
  "use strict";
  var root = (document.querySelector('link[rel="manifest"]') || {}).getAttribute
    ? document.querySelector('link[rel="manifest"]').getAttribute("href").replace(/\/manifest\.webmanifest$/, "")
    : "";

  // Формы с вопросом перед отправкой
  document.addEventListener("submit", function (e) {
    var form = e.target.closest("form[data-confirm]");
    if (form && !window.confirm(form.getAttribute("data-confirm"))) e.preventDefault();
  });

  // «Назад» на странице ошибки
  document.addEventListener("click", function (e) {
    var back = e.target.closest("[data-back]");
    if (back && window.history.length > 1) { e.preventDefault(); window.history.back(); }
    var copy = e.target.closest("[data-copy]");
    if (copy) {
      var input = document.getElementById(copy.getAttribute("data-copy"));
      input.select();
      var done = function () { copy.textContent = "Скопировано"; };
      if (navigator.clipboard) navigator.clipboard.writeText(input.value).then(done, function () { document.execCommand("copy"); done(); });
      else { document.execCommand("copy"); done(); }
    }
  });

  // Пока бланк разбирается — страница обновляется сама
  var reload = document.querySelector("[data-reload]");
  if (reload) setTimeout(function () { window.location.reload(); }, 1000 * Number(reload.getAttribute("data-reload")));

  // Выбранный файл — его имя рядом с кнопкой
  document.querySelectorAll('input[type="file"]').forEach(function (input) {
    input.addEventListener("change", function () {
      var label = input.closest("label");
      if (label && input.files.length) label.classList.add("chosen");
    });
  });

  // Фигурка: подсказка при наведении, блок органа по щелчку или касанию
  var figure = document.querySelector(".body-figure");
  if (figure) {
    var tip = document.getElementById("organ-tip");
    var wrap = figure.parentNode;
    var show = function (g, e) {
      tip.innerHTML = "";
      var b = document.createElement("b"); b.textContent = g.getAttribute("data-name");
      tip.appendChild(b); tip.appendChild(document.createTextNode(g.getAttribute("data-line")));
      tip.hidden = false;
      var box = wrap.getBoundingClientRect();
      var x = (e && e.clientX ? e.clientX : g.getBoundingClientRect().right) - box.left + 12;
      var y = (e && e.clientY ? e.clientY : g.getBoundingClientRect().top) - box.top + 12;
      tip.style.left = Math.min(x, box.width - 200) + "px";
      tip.style.top = y + "px";
    };
    var open = function (g) {
      var id = g.getAttribute("data-organ");
      figure.querySelectorAll(".organ.selected").forEach(function (o) { o.classList.remove("selected"); });
      g.classList.add("selected");
      document.querySelectorAll(".organ-panel").forEach(function (p) { p.hidden = p.id !== "organ-" + id; });
      var hint = document.getElementById("organ-hint"); if (hint) hint.hidden = true;
      var panel = document.getElementById("organ-" + id);
      if (panel && window.matchMedia("(max-width: 700px)").matches) panel.scrollIntoView({ behavior: "smooth", block: "start" });
    };
    figure.querySelectorAll(".organ").forEach(function (g) {
      g.addEventListener("mousemove", function (e) { show(g, e); });
      g.addEventListener("mouseleave", function () { tip.hidden = true; });
      g.addEventListener("focus", function () { show(g); });
      g.addEventListener("blur", function () { tip.hidden = true; });
      g.addEventListener("click", function () { tip.hidden = true; open(g); });
      g.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(g); } });
    });
  }

  // Работник нужен, чтобы телефон предлагал «Установить приложение». Ничего не хранит.
  if ("serviceWorker" in navigator && root !== null) {
    navigator.serviceWorker.register(root + "/sw.js", { scope: root + "/" }).catch(function () {});
  }
})();
