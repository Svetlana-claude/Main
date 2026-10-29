// Картинки: дерево «проект → папка», сетка и просмотрщик.
(function () {
  const root = window.SITE.root;
  const $ = (id) => document.getElementById(id);
  const tree = $("pic-tree"), grid = $("pic-grid"), note = $("pic-note");
  const title = $("pic-title"), count = $("pic-count");
  const search = $("pic-search"), sortBox = $("pic-sort"), sizeBox = $("pic-size");
  const side = $("pics-side"), toggle = $("pic-toggle");
  let data = {groups: []};
  let shown = [];                       // кадры в сетке, в её порядке — для листания
  const sel = {project: null, folder: null};

  function remember(key, value) { try { localStorage.setItem("pictures:" + key, value); } catch (e) { /* закрыто */ } }
  function recall(key) { try { return localStorage.getItem("pictures:" + key); } catch (e) { return null; } }

  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }
  function q(src) { return encodeURIComponent(src); }
  function size(b) {
    if (b < 1024) return b + " Б";
    const units = ["КБ", "МБ", "ГБ"];
    let v = b, i = -1;
    do { v /= 1024; i++; } while (v >= 1024 && i < 2);
    return (v < 10 ? v.toFixed(1) : Math.round(v)).toString().replace(".", ",") + " " + units[i];
  }
  function when(iso) {
    return new Date(iso).toLocaleDateString("ru-RU", {day: "2-digit", month: "2-digit", year: "numeric"});
  }

  // ── Дерево ──
  function node(label, n, active, onClick, cls) {
    const b = el("button", "pic-node " + (cls || "") + (active ? " is-current" : ""));
    b.type = "button";
    b.append(el("span", "pic-node-name", label), el("span", "pic-node-count", n));
    if (active) b.setAttribute("aria-current", "true");
    b.addEventListener("click", onClick);
    return b;
  }
  function pick(project, folder) {
    sel.project = project; sel.folder = folder;
    remember("sel", JSON.stringify(sel));
    // На телефоне список закрывается, когда выбрано окончательно: у проекта
    // с папками он остаётся открытым — выбрать папку
    const g = data.groups.find((x) => x.id === project);
    if (project === null || folder !== null || !g || g.folders.length < 2) {
      side.classList.remove("open"); toggle.setAttribute("aria-expanded", "false");
    }
    draw();
  }
  function drawTree() {
    tree.textContent = "";
    const total = data.groups.reduce((s, g) => s + g.count, 0);
    tree.append(node("Все картинки", total, sel.project === null, () => pick(null, null), "all"));
    for (const g of data.groups) {
      const open = sel.project === g.id;
      tree.append(node(g.name, g.count, open && sel.folder === null, () => pick(g.id, null), "proj"));
      if (open && !(g.folders.length === 1 && g.folders[0].path === "")) {
        // Вложенная папка — сдвинута вправо и подписана своим именем; полный
        // путь — в подсказке и в заголовке над сеткой
        // Вложенная папка — сдвинута под ближайшую показанную и подписана
        // путём от неё; полный путь — в подсказке и в заголовке над сеткой
        const depth = {};
        for (const f of g.folders) {
          let label = f.title, level = 1;
          if (f.path) {
            const parents = g.folders.filter((p) => p.path && f.path.startsWith(p.path + "/"));
            const near = parents.sort((a, b) => b.path.length - a.path.length)[0];
            if (near) { label = f.path.slice(near.path.length + 1); level = depth[near.path] + 1; }
            depth[f.path] = level;
          }
          const b = node(label, f.images.length, sel.folder === f.path, () => pick(g.id, f.path), "folder");
          b.style.setProperty("--depth", level);
          b.title = f.title;
          tree.append(b);
        }
      }
    }
    if (!data.groups.length) tree.append(el("p", "muted", "В проектах картинок нет."));
  }

  // ── Сетка ──
  function collect() {
    const items = [];
    const needle = search.value.trim().toLowerCase().replace(/ё/g, "е");
    for (const g of data.groups) {
      if (sel.project !== null && g.id !== sel.project) continue;
      for (const f of g.folders) {
        if (sel.folder !== null && f.path !== sel.folder) continue;
        for (const im of f.images) {
          if (needle && !im.name.toLowerCase().replace(/ё/g, "е").includes(needle)) continue;
          items.push(Object.assign({project: g.name, folder: f.path}, im));
        }
      }
    }
    const by = {
      new: (a, b) => b.mtime.localeCompare(a.mtime),
      old: (a, b) => a.mtime.localeCompare(b.mtime),
      name: (a, b) => a.name.localeCompare(b.name, "ru", {numeric: true}),
      big: (a, b) => b.size - a.size,
    }[sortBox.value] || ((a, b) => b.mtime.localeCompare(a.mtime));
    return items.sort(by);
  }
  function where(im) { return im.project + (im.folder ? " / " + im.folder : ""); }

  function drawGrid() {
    shown = collect();
    grid.textContent = "";
    const g = data.groups.find((x) => x.id === sel.project);
    title.textContent = g ? (sel.folder !== null ? g.name + " / " + (sel.folder || "в корне проекта") : g.name) : "Все картинки";
    count.textContent = shown.length ? shown.length + " шт." : "";
    if (!shown.length) {
      grid.append(el("p", "muted", search.value.trim() ? "По такому имени ничего нет." : "Здесь картинок нет."));
      return;
    }
    shown.forEach((im, i) => {
      const tile = el("button", "pic-tile");
      tile.type = "button";
      tile.title = im.name;
      const frame = el("span", "pic-frame");
      const img = document.createElement("img");
      img.loading = "lazy"; img.decoding = "async"; img.alt = im.name;
      img.src = root + "/pictures/thumb?src=" + q(im.src);
      img.addEventListener("error", () => { frame.textContent = "не открыть"; frame.classList.add("broken"); });
      frame.append(img);
      tile.append(frame, el("span", "pic-name", im.name),
                  el("span", "pic-meta", size(im.size) + " · " + when(im.mtime) + (sel.project === null ? " · " + im.project : "")));
      tile.addEventListener("click", () => openViewer(i));
      grid.append(tile);
    });
  }
  function draw() { drawTree(); drawGrid(); }

  async function load() {
    try {
      const r = await fetch(root + "/pictures/list", {credentials: "same-origin"});
      if (!r.ok) throw new Error();
      data = await r.json();
    } catch (e) {
      note.textContent = "Не получилось загрузить список — обнови страницу.";
      note.hidden = false;
      tree.textContent = "";
      return;
    }
    if (data.truncated) {
      note.textContent = "Картинок больше " + data.limit + " — показаны не все.";
      note.hidden = false;
    }
    if (sel.project !== null && !data.groups.some((g) => g.id === sel.project)) { sel.project = null; sel.folder = null; }
    draw();
  }

  // ── Просмотрщик ──
  const viewer = $("pic-viewer"), img = $("v-img"), stage = $("v-stage");
  let at = 0, zoom = 0;                 // zoom 0 — вписано в окно
  const STEPS = [0.25, 0.5, 0.75, 1, 1.5, 2, 3, 4];

  function setZoom(z) {
    zoom = z;
    if (!z) {
      img.classList.add("fit"); img.style.width = "";
      $("v-zoom").textContent = "вписано";
    } else {
      img.classList.remove("fit");
      img.style.width = Math.round((img.naturalWidth || 800) * z) + "px";
      $("v-zoom").textContent = Math.round(z * 100) + " %";
    }
  }
  function current() {
    if (!zoom) return img.naturalWidth ? img.clientWidth / img.naturalWidth : 1;
    return zoom;
  }
  function step(dir) {
    const now = current();
    const next = dir > 0 ? STEPS.find((s) => s > now + 0.01) : [...STEPS].reverse().find((s) => s < now - 0.01);
    if (next) setZoom(next);
  }
  function show(i) {
    if (!shown.length) return;
    at = (i + shown.length) % shown.length;
    const im = shown[at];
    img.alt = im.name;
    img.src = root + "/pictures/view?src=" + q(im.src);
    $("v-name").textContent = im.name;
    $("v-where").textContent = where(im) + " · " + size(im.size);
    $("v-download").href = root + "/pictures/file?src=" + q(im.src);
    $("v-pos").textContent = (at + 1) + " из " + shown.length;
    const many = shown.length > 1;
    $("v-prev").hidden = !many; $("v-next").hidden = !many;
    setZoom(0);
    stage.scrollTo(0, 0);
  }
  function openViewer(i) {
    show(i);
    if (!viewer.open) viewer.showModal();
  }
  function closeViewer() {
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
    viewer.close();
    img.removeAttribute("src");
  }
  img.addEventListener("load", () => { if (zoom) setZoom(zoom); });
  img.addEventListener("dblclick", () => setZoom(zoom ? 0 : 1));
  $("v-prev").addEventListener("click", () => show(at - 1));
  $("v-next").addEventListener("click", () => show(at + 1));
  $("v-in").addEventListener("click", () => step(1));
  $("v-out").addEventListener("click", () => step(-1));
  $("v-fit").addEventListener("click", () => setZoom(zoom ? 0 : 1));
  $("v-close").addEventListener("click", closeViewer);
  $("v-full").addEventListener("click", () => {
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
    else if (viewer.requestFullscreen) viewer.requestFullscreen().catch(() => {});
  });
  if (!document.fullscreenEnabled) $("v-full").hidden = true;   // iPhone не умеет
  viewer.addEventListener("cancel", (e) => { e.preventDefault(); closeViewer(); });
  viewer.addEventListener("keydown", (e) => {
    if (e.key === "ArrowLeft") show(at - 1);
    else if (e.key === "ArrowRight") show(at + 1);
    else if (e.key === "+" || e.key === "=") step(1);
    else if (e.key === "-") step(-1);
    else if (e.key === "0") setZoom(0);
    else if (e.key === "1") setZoom(1);
    else if (e.key === "f" || e.key === "F" || e.key === "а" || e.key === "А") $("v-full").click();
    else return;
    e.preventDefault();
  });
  // Листание пальцем, когда картинка вписана
  let touchX = null;
  stage.addEventListener("touchstart", (e) => { touchX = e.touches.length === 1 && !zoom ? e.touches[0].clientX : null; }, {passive: true});
  stage.addEventListener("touchend", (e) => {
    if (touchX === null) return;
    const dx = e.changedTouches[0].clientX - touchX;
    if (Math.abs(dx) > 50) show(at + (dx < 0 ? 1 : -1));
    touchX = null;
  });

  // ── Управление ──
  function setSize(v) {
    grid.className = "pic-grid size-" + v;
    remember("size", v);
  }
  sortBox.addEventListener("change", () => { remember("sort", sortBox.value); drawGrid(); });
  sizeBox.addEventListener("input", () => setSize(sizeBox.value));
  search.addEventListener("input", drawGrid);
  toggle.addEventListener("click", () => {
    const open = side.classList.toggle("open");
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
  });

  try {
    const s = JSON.parse(recall("sel") || "null");
    if (s) { sel.project = s.project; sel.folder = s.folder; }
  } catch (e) { /* пусто */ }
  if (recall("sort")) sortBox.value = recall("sort");
  if (recall("size")) { sizeBox.value = recall("size"); setSize(sizeBox.value); }
  load();
})();
