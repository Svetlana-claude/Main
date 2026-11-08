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

  // Работник нужен, чтобы телефон предлагал «Установить приложение». Ничего не хранит.
  if ("serviceWorker" in navigator && root !== null) {
    navigator.serviceWorker.register(root + "/sw.js", { scope: root + "/" }).catch(function () {});
  }
})();
