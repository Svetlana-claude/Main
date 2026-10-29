// Чат и темы проектов: отправка, дописка, ответ потоком, что Claude делает,
// переименование, удаление, галочки проекта
(function () {
  "use strict";
  var site = window.SITE || {};
  var body = document.body;

  // Подтверждение для форм с вопросом (удаление)
  document.querySelectorAll("form[data-confirm]").forEach(function (form) {
    form.addEventListener("submit", function (e) {
      if (!confirm(form.dataset.confirm)) e.preventDefault();
    });
  });

  // Телефон: из разговора — к списку
  var toList = document.getElementById("to-list");
  if (toList) toList.addEventListener("click", function () { body.classList.toggle("show-list"); });

  // Модель и галочки проекта меняются сразу при выборе
  var model = document.getElementById("model");
  if (model) model.addEventListener("change", function () { model.form.submit(); });
  var access = document.getElementById("access-form");
  if (access) access.addEventListener("change", function () { access.submit(); });

  // Переименование: карандаш открывает поле
  var renameBtn = document.getElementById("rename-btn");
  var renameForm = document.getElementById("rename-form");
  if (renameBtn && renameForm) {
    renameBtn.addEventListener("click", function () {
      renameForm.hidden = !renameForm.hidden;
      if (!renameForm.hidden) document.getElementById("rename-input").select();
    });
    document.getElementById("rename-cancel").addEventListener("click", function () {
      renameForm.hidden = true;
      renameBtn.focus();
    });
  }

  // Переименование проекта: то же, у названия проекта
  var projBtn = document.getElementById("proj-rename-btn");
  var projForm = document.getElementById("proj-rename-form");
  if (projBtn && projForm) {
    projBtn.addEventListener("click", function () {
      projForm.hidden = !projForm.hidden;
      projBtn.setAttribute("aria-expanded", projForm.hidden ? "false" : "true");
      if (!projForm.hidden) document.getElementById("proj-rename-input").select();
    });
    document.getElementById("proj-rename-cancel").addEventListener("click", function () {
      projForm.hidden = true;
      projBtn.setAttribute("aria-expanded", "false");
      projBtn.focus();
    });
  }

  // Файлы проекта: загрузка с ходом в процентах, список обновляется сам
  var filesBox = document.getElementById("files");
  var filesBase = filesBox ? site.root + "/projects/" + filesBox.dataset.project + "/files" : "";

  function refreshFiles() {
    if (!filesBox) return Promise.resolve();
    return fetch(filesBase + "/list", {credentials: "same-origin", cache: "no-store"})
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) { if (data) filesBox.innerHTML = data.html; })
      .catch(function () {});
  }

  function uploadMsg(text, ok) {
    var msg = document.getElementById("upload-msg");
    if (!msg) return;
    msg.textContent = text;
    msg.className = "small " + (ok ? "ok" : "error");
    msg.hidden = !text;
  }

  if (filesBox) {
    filesBox.addEventListener("change", function (e) {
      if (e.target.id !== "upload-input" || !e.target.files.length) return;
      var form = e.target.form;
      form.elements.back.value = location.pathname;
      var xhr = new XMLHttpRequest();
      xhr.open("POST", form.action);
      xhr.setRequestHeader("X-Upload", "1");
      xhr.upload.onprogress = function (ev) {
        if (ev.lengthComputable) uploadMsg("Загружаю… " + Math.floor(ev.loaded * 100 / ev.total) + "%", true);
      };
      xhr.onload = function () {
        var data = {};
        try { data = JSON.parse(xhr.responseText); } catch (err) {}
        refreshFiles().then(function () {
          uploadMsg(data.message || (xhr.status === 403 ? "Нет доступа — обнови страницу" : "Не загрузилось"),
                    xhr.status === 200);
        });
      };
      xhr.onerror = function () { uploadMsg("Не загрузилось — проверь связь и попробуй ещё раз", false); };
      uploadMsg("Загружаю…", true);
      xhr.send(new FormData(form));
    });
  }

  var composer = document.getElementById("composer");
  if (!composer) return;
  var conv = composer.dataset.conv;
  var count = composer.dataset.count;
  var feed = document.getElementById("feed");
  var text = document.getElementById("text");
  var sendBtn = document.getElementById("send-btn");
  var errorBox = document.getElementById("send-error");
  var base = site.root + "/chat/" + conv;
  var source = null;

  function nearBottom() {
    return feed.scrollHeight - feed.scrollTop - feed.clientHeight < 120;
  }
  function toBottom() { feed.scrollTop = feed.scrollHeight; }

  function setRunning(on) { sendBtn.textContent = on ? "Дописать" : "Отправить"; }

  function showError(msg) {
    errorBox.textContent = msg || "";
    errorBox.hidden = !msg;
  }

  function refresh() {
    var stick = nearBottom();
    return fetch(base + "/feed?n=" + count, {credentials: "same-origin", cache: "no-store"})
      .then(function (r) {
        if (!r.ok) { location.reload(); throw new Error("нет доступа"); }
        return r.json();
      })
      .then(function (data) {
        feed.innerHTML = data.html;
        document.getElementById("weight").textContent = data.weight;
        document.getElementById("talk-title").textContent = data.title;
        var item = document.querySelector(".conv-list a[aria-current=page] .conv-title");
        if (item) item.textContent = data.title;
        setRunning(data.running);
        if (stick) toBottom();
        return data;
      });
  }

  function listen() {
    if (source) return;
    source = new EventSource(base + "/stream");
    source.onmessage = function (e) {
      var ev = JSON.parse(e.data);
      var live = document.getElementById("live-text");
      var status = document.getElementById("live-status");
      if (ev.t === "snapshot" && live) {
        live.textContent = ev.x;
        if (status && ev.s) status.textContent = ev.s;
      } else if (ev.t === "status") {
        if (status) status.textContent = ev.x;
      } else if (ev.t === "start") {
        if (live) live.textContent = "";
      } else if (ev.t === "delta") {
        var stick = nearBottom();
        if (live) live.textContent += ev.x;
        if (stick) toBottom();
      } else if (ev.t === "added" || ev.t === "saved") {
        refresh();
        refreshFiles();
      } else if (ev.t === "done") {
        source.close();
        source = null;
        refresh();
        refreshFiles();
      }
    };
    source.onerror = function () {
      // Связь прервалась: закрываем и сверяемся с сервером
      if (source) source.close();
      source = null;
      setTimeout(function () {
        refresh().then(function (data) { if (data.running) listen(); }).catch(function () {});
      }, 2000);
    };
  }

  function send() {
    var value = text.value.trim();
    if (!value) return;
    sendBtn.disabled = true;
    showError("");
    var form = new URLSearchParams();
    form.set("text", value);
    form.set("csrf", site.csrf);
    fetch(base + "/send", {method: "POST", credentials: "same-origin", body: form})
      .then(function (r) { return r.json().then(function (data) { return {ok: r.ok, data: data}; }); })
      .then(function (res) {
        if (!res.ok) { showError(res.data.error || "Не отправилось"); return; }
        text.value = "";
        toBottom();
        return refresh().then(function () { toBottom(); listen(); });
      })
      .catch(function () { showError("Не отправилось — проверь связь и попробуй ещё раз"); })
      .then(function () { sendBtn.disabled = false; text.focus(); });
  }

  composer.addEventListener("submit", function (e) { e.preventDefault(); send(); });
  text.addEventListener("keydown", function (e) {
    // Ctrl+Enter (на Mac — Cmd+Enter) — отправить, Enter — новая строка
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && !e.isComposing) { e.preventDefault(); send(); }
  });

  if (!location.hash) toBottom();
  if (document.getElementById("live")) listen();
})();
