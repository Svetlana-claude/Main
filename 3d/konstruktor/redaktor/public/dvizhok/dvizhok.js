// Движок показа модели. Один и тот же код работает в редакторе, в предпросмотре
// и в выгруженном просмотрщике — поэтому они выглядят одинаково.
//
// Все координаты в описании — в метрах, ось Y вверх, начало — главная точка
// подвеса. Точки (position, label, anchors, pivot, точки трубок) задаются
// в общих координатах модели в собранном виде; движок сам пересчитывает их
// в координаты родителя.

import * as THREE from 'three';
import { OrbitControls } from 'three';
import { proverit, spisokDetaley, ANIMACII } from './format.js';

const DEG = Math.PI / 180;
const v3 = (a, d = [0, 0, 0]) => new THREE.Vector3(...(Array.isArray(a) ? a : d));
const plavno = (x) => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2);
const zazhat = (x, a, b) => Math.min(b, Math.max(a, x));

// ---------- Формы ----------

// Профиль крыла: точки замкнутого контура, x — доля хорды от передней кромки,
// y — в долях хорды. Верх идёт от задней кромки к передней, низ — обратно.
function profil(n, tolshchina, progib = 0) {
  const verh = [];
  const niz = [];
  for (let i = 0; i < n; i++) {
    const x = (1 - Math.cos((i / (n - 1)) * Math.PI)) / 2;
    const yt = 5 * tolshchina * (0.2969 * Math.sqrt(x) - 0.126 * x - 0.3516 * x * x + 0.2843 * x ** 3 - 0.1036 * x ** 4);
    const yc = progib * 4 * x * (1 - x);
    verh.push({ x, y: yc + yt, niz: false });
    niz.push({ x, y: yc - yt, niz: true });
  }
  // Контур: верх от хвоста к носу, затем низ от носа к хвосту (без повтора носа и хвоста).
  return [...verh.slice().reverse(), ...niz.slice(1, -1)];
}

// Сетка «профиль, протянутый по станциям». Станция: центр, хорда, вектор «вверх»,
// множитель толщины. Торцы закрываются веером. Возвращает геометрию и индексы.
function protyanut(stancii, kontur, { torcy = true } = {}) {
  const pos = [];
  const ves = [];
  const m = kontur.length;
  for (const s of stancii) {
    for (const t of kontur) {
      const p = s.centr.clone()
        .add(new THREE.Vector3(0, 0, s.horda * (0.5 - t.x)))
        .addScaledVector(s.verh, t.y * s.horda * (s.tolsh ?? 1));
      pos.push(p.x, p.y, p.z);
      ves.push(s.ves ?? 1);
    }
  }
  const idx = [];
  for (let i = 0; i < stancii.length - 1; i++) {
    if (stancii[i].razryv) continue;
    for (let j = 0; j < m; j++) {
      const a = i * m + j;
      const b = i * m + ((j + 1) % m);
      const c = (i + 1) * m + j;
      const d = (i + 1) * m + ((j + 1) % m);
      idx.push(a, c, b, b, c, d);
    }
  }
  if (torcy) {
    for (const [st, obr] of [[0, true], [stancii.length - 1, false]]) {
      const c = new THREE.Vector3();
      for (let j = 0; j < m; j++) c.add(new THREE.Vector3(pos[(st * m + j) * 3], pos[(st * m + j) * 3 + 1], pos[(st * m + j) * 3 + 2]));
      c.divideScalar(m);
      const ci = pos.length / 3;
      pos.push(c.x, c.y, c.z);
      ves.push(0);
      for (let j = 0; j < m; j++) {
        const a = st * m + j;
        const b = st * m + ((j + 1) % m);
        if (obr) idx.push(ci, b, a); else idx.push(ci, a, b);
      }
    }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute('ves', new THREE.Float32BufferAttribute(ves, 1));
  g.setIndex(idx);
  g.computeVertexNormals();
  return g;
}

function formaKrylo(f) {
  const span = f.span ?? 4;
  const horda = f.chord ?? 1;
  const taper = f.taper ?? 1;
  const sweep = (f.sweep ?? 0) * DEG;
  const dih = (f.dihedral ?? 0) * DEG;
  const n = f.segments ?? 16;
  const kontur = profil(14, f.thickness ?? 0.12, f.camber ?? 0.02);
  const st = [];
  for (let i = 0; i <= n; i++) {
    const s = -1 + (2 * i) / n;
    const x = (s * span) / 2;
    const ax = Math.abs(x);
    st.push({
      centr: new THREE.Vector3(x, ax * Math.tan(dih), -ax * Math.tan(sweep)),
      horda: horda * (1 - (1 - taper) * Math.abs(s)),
      verh: new THREE.Vector3(-Math.sign(x) * Math.sin(dih), Math.cos(dih), 0),
    });
  }
  return { geometrii: [protyanut(st, kontur)] };
}

// Купол-крыло: секции по размаху, в каждой несколько делений; ячейки надуваются
// между нервюрами. Отдаёт якоря для строп (низ нервюр) и для тормозных строп.
function formaKupolKrylo(f) {
  const N = f.sections ?? 9;
  const D = f.divisions ?? 12;
  const S = f.span ?? 8;
  const C = f.chord ?? 3;
  const A = Math.max(0.01, f.arc ?? 1);
  const kontur = profil(16, f.thickness ?? 0.16, 0.03);
  const R = ((S / 2) ** 2 + A * A) / (2 * A);
  const tMax = Math.asin(zazhat(S / 2 / R, -1, 1));
  const st = [];
  const nervyury = [];
  for (let sec = 0; sec < N; sec++) {
    for (let d = 0; d <= D; d++) {
      const frac = d / D;
      const s = -1 + (2 * (sec + frac)) / N;
      const t = s * tMax;
      const vozd = Math.sin(Math.PI * frac);
      st.push({
        centr: new THREE.Vector3(R * Math.sin(t), R * Math.cos(t) - R, 0),
        horda: C,
        verh: new THREE.Vector3(Math.sin(t), Math.cos(t), 0),
        tolsh: 0.72 + 0.28 * vozd,
        ves: vozd,
        razryv: d === D,
        sekciya: sec,
      });
      if (d === 0 || (sec === N - 1 && d === D)) nervyury.push(st.length - 1);
    }
  }
  const g = protyanut(st, kontur);
  // Полосы по секциям — цвета вершин.
  const cveta = (f.colors && f.colors.length ? f.colors : null);
  if (cveta) {
    const m = kontur.length;
    const col = [];
    const c = new THREE.Color();
    for (const s of st) {
      c.set(cveta[s.sekciya % cveta.length]);
      for (let j = 0; j < m; j++) col.push(c.r, c.g, c.b);
    }
    c.set(cveta[0]);
    col.push(c.r, c.g, c.b, c.r, c.g, c.b);
    g.setAttribute('color', new THREE.Float32BufferAttribute(col, 3));
  }
  // Якоря: нижние точки нервюр в рядах A–D и задняя кромка внешних нервюр.
  const m = kontur.length;
  const nizhnyaya = (x) => {
    let luch = 0;
    let best = 9;
    kontur.forEach((t, j) => {
      if (t.niz && Math.abs(t.x - x) < best) { best = Math.abs(t.x - x); luch = j; }
    });
    return luch;
  };
  const ryady = (f.rows ?? [0.06, 0.3, 0.55, 0.8]).map(nizhnyaya);
  const kromka = [];
  for (const ni of nervyury) for (const j of ryady) kromka.push({ index: ni * m + j });
  const hvostJ = nizhnyaya(0.97);
  const khvost = [];
  nervyury.forEach((ni, k) => {
    const s = -1 + (2 * k) / N;
    if (Math.abs(s) > 0.25) khvost.push({ index: ni * m + hvostJ });
  });
  return { geometrii: [g], deform: true, vertexColors: !!cveta, yakorya: { kromka, khvost } };
}

// Круглый купол: клинья от вершины к кромке, полотно выпирает между швами.
function formaKupolKruglyy(f) {
  const N = f.sections ?? 8;
  const D = f.divisions ?? 12;
  const R = (f.diameter ?? 8) / 2;
  const H = f.height ?? R * 0.7;
  const M = f.rings ?? 14;
  const polyus = f.vent ?? 0.06;
  const pos = [];
  const ves = [];
  const kolonok = N * D;
  for (let i = 0; i <= M; i++) {
    const r = polyus + (1 - polyus) * (i / M);
    for (let k = 0; k < kolonok; k++) {
      const frac = (k % D) / D;
      const phi = (k / kolonok) * Math.PI * 2;
      const vypukl = 1 + 0.05 * Math.sin(Math.PI * frac) * Math.sin((Math.PI * i) / M + 0.3);
      const rr = R * r * vypukl;
      const y = H * (1 - r * r) * (1 + 0.02 * Math.sin(Math.PI * frac));
      pos.push(rr * Math.cos(phi), y, rr * Math.sin(phi));
      ves.push(Math.sin(Math.PI * frac) * Math.sin((Math.PI * i) / M + 0.2));
    }
  }
  const idx = [];
  for (let i = 0; i < M; i++) {
    for (let k = 0; k < kolonok; k++) {
      const a = i * kolonok + k;
      const b = i * kolonok + ((k + 1) % kolonok);
      const c = (i + 1) * kolonok + k;
      const d = (i + 1) * kolonok + ((k + 1) % kolonok);
      idx.push(a, b, c, b, d, c);
    }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute('ves', new THREE.Float32BufferAttribute(ves, 1));
  g.setIndex(idx);
  g.computeVertexNormals();
  const kromka = [];
  for (let s = 0; s < N; s++) kromka.push({ index: M * kolonok + s * D });
  return { geometrii: [g], deform: true, yakorya: { kromka, khvost: kromka.slice() } };
}

// Капсула между двумя точками — для рук, ног, лямок.
function otrezok(a, b, r) {
  const dl = a.distanceTo(b);
  const g = new THREE.CapsuleGeometry(r, Math.max(0.001, dl), 4, 10);
  const q = new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), b.clone().sub(a).normalize());
  g.applyQuaternion(q);
  const c = a.clone().add(b).multiplyScalar(0.5);
  g.translate(c.x, c.y, c.z);
  return g;
}

// Фигура человека из простых тел. Начало — середина таза.
function formaChelovek(f) {
  const k = (f.height ?? 1.8) / 1.8;
  const P = (x, y, z) => new THREE.Vector3(x * k, y * k, z * k);
  const poza = f.pose ?? 'stoit';
  const sk = {
    visit: { lok: [0.3, 0.74, 0.04], kist: [0.26, 0.98, 0.02], kol: [0.12, -0.4, 0.14], stopa: [0.12, -0.82, 0.08] },
    stoit: { lok: [0.24, 0.22, 0], kist: [0.25, -0.05, 0.04], kol: [0.1, -0.43, 0.01], stopa: [0.1, -0.86, 0] },
    sidit: { lok: [0.24, 0.22, 0.1], kist: [0.18, 0.02, 0.36], kol: [0.12, -0.02, 0.44], stopa: [0.12, -0.44, 0.48] },
  }[poza] || {};
  const odezhda = [];
  const kozha = [];
  odezhda.push(otrezok(P(0, 0.05, 0), P(0, 0.44, 0), 0.15 * k).scale(1, 1, 0.72));
  odezhda.push(otrezok(P(-0.1, 0.02, 0), P(0.1, 0.02, 0), 0.12 * k));
  kozha.push(new THREE.SphereGeometry(0.105 * k, 20, 14).translate(0, 0.72 * k, 0.01 * k));
  odezhda.push(otrezok(P(0, 0.55, 0), P(0, 0.62, 0), 0.05 * k));
  for (const s of [-1, 1]) {
    const pl = P(0.19 * s, 0.5, 0);
    const lok = P(sk.lok[0] * s, sk.lok[1], sk.lok[2]);
    const kist = P(sk.kist[0] * s, sk.kist[1], sk.kist[2]);
    odezhda.push(otrezok(pl, lok, 0.052 * k), otrezok(lok, kist, 0.045 * k));
    kozha.push(new THREE.SphereGeometry(0.045 * k, 10, 8).translate(kist.x, kist.y, kist.z));
    const bed = P(0.1 * s, 0, 0);
    const kol = P(sk.kol[0] * s, sk.kol[1], sk.kol[2]);
    const st = P(sk.stopa[0] * s, sk.stopa[1], sk.stopa[2]);
    odezhda.push(otrezok(bed, kol, 0.075 * k), otrezok(kol, st, 0.058 * k));
    odezhda.push(new THREE.BoxGeometry(0.1 * k, 0.07 * k, 0.24 * k).translate(st.x, st.y - 0.03 * k, st.z + 0.06 * k));
  }
  const kaska = f.helmet ? [new THREE.SphereGeometry(0.118 * k, 20, 10, 0, Math.PI * 2, 0, Math.PI * 0.55).translate(0, 0.73 * k, 0)] : [];
  const ruki = [-1, 1].map((s) => ({ local: P(sk.kist[0] * s, sk.kist[1], sk.kist[2]) }));
  return {
    geometrii: odezhda,
    dop: [
      { geometrii: kozha, color: f.skin ?? '#e9c6a5' },
      ...(kaska.length ? [{ geometrii: kaska, color: f.helmet }] : []),
    ],
    yakorya: { ruki },
  };
}

function postroitFormu(f, kVLokalnye) {
  switch (f.type) {
    case 'group':
    case 'lines':
      return { geometrii: [] };
    case 'box':
      return { geometrii: [new THREE.BoxGeometry(...(f.size ?? [1, 1, 1]))] };
    case 'cylinder':
      return { geometrii: [new THREE.CylinderGeometry(f.radiusTop ?? f.radius ?? 0.5, f.radiusBottom ?? f.radius ?? 0.5, f.height ?? 1, f.segments ?? 32)] };
    case 'cone':
      return { geometrii: [new THREE.ConeGeometry(f.radius ?? 0.5, f.height ?? 1, f.segments ?? 32)] };
    case 'sphere':
      return { geometrii: [new THREE.SphereGeometry(f.radius ?? 0.5, 32, 18)] };
    case 'capsule':
      return { geometrii: [new THREE.CapsuleGeometry(f.radius ?? 0.2, f.length ?? 1, 6, 18)] };
    case 'torus':
      return { geometrii: [new THREE.TorusGeometry(f.radius ?? 0.5, f.tube ?? 0.05, 12, 48, (f.arc ?? 360) * DEG)] };
    case 'lathe':
      return { geometrii: [new THREE.LatheGeometry((f.points ?? [[0, 0], [0.5, 0], [0, 1]]).map(([r, y]) => new THREE.Vector2(r, y)), f.segments ?? 40)] };
    case 'tube': {
      const tochki = (f.points ?? [[0, 0, 0], [0, 1, 0]]).map((p) => kVLokalnye(v3(p)));
      const kriv = new THREE.CatmullRomCurve3(tochki);
      return { geometrii: [new THREE.TubeGeometry(kriv, Math.max(8, tochki.length * 12), f.radius ?? 0.02, 8, false)] };
    }
    case 'wing':
      return formaKrylo(f);
    case 'kupol':
      return f.vid === 'kruglyy' ? formaKupolKruglyy(f) : formaKupolKrylo(f);
    case 'chelovek':
      return formaChelovek(f);
    default:
      return { geometrii: [] };
  }
}

// ---------- Стили просмотрщика ----------

const STIL = `
.dv{position:relative;display:flex;width:100%;height:100%;font:14px/1.4 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;color:#1f2933;background:#f4f6f8;overflow:hidden}
.dv *{box-sizing:border-box}
.dv-scena{position:relative;flex:1;min-width:0;background:linear-gradient(180deg,#cfe0ee 0%,#eef3f7 60%,#f7f8f6 100%)}
.dv-scena canvas{display:block;width:100%;height:100%;outline:none;touch-action:none}
.dv-sloy{position:absolute;inset:0;pointer-events:none}
.dv-sloy svg{position:absolute;inset:0;width:100%;height:100%}
.dv-num{position:absolute;width:24px;height:24px;margin:-12px 0 0 -12px;border-radius:50%;background:#fff;border:2px solid #2f5d8a;color:#2f5d8a;font-weight:700;font-size:12px;display:flex;align-items:center;justify-content:center;pointer-events:auto;cursor:pointer;user-select:none;box-shadow:0 1px 3px rgba(0,0,0,.25)}
.dv-num.akt{background:#e8731c;border-color:#e8731c;color:#fff;z-index:2}
.dv-panel{width:340px;flex:none;display:flex;flex-direction:column;background:#fff;border-left:1px solid #dde3e8;min-height:0}
.dv-upr{padding:12px 14px;border-bottom:1px solid #e6eaee}
.dv-upr h1{font-size:16px;margin:0 0 2px}
.dv-masht{font-size:12px;color:#66727e;margin-bottom:8px}
.dv-ryad{display:flex;align-items:center;gap:8px;margin:6px 0;flex-wrap:wrap}
.dv-ryad label{min-width:92px;font-size:13px}
.dv-ryad input[type=range]{flex:1;min-width:100px;accent-color:#2f5d8a}
.dv button{font:inherit;font-size:13px;padding:4px 10px;border:1px solid #c5ced6;border-radius:6px;background:#f7f9fa;color:#1f2933;cursor:pointer}
.dv button:hover{background:#eef2f5}
.dv button.vkl{background:#2f5d8a;border-color:#2f5d8a;color:#fff}
.dv-zag{font-size:12px;font-weight:600;color:#66727e;text-transform:uppercase;letter-spacing:.04em;margin:10px 0 4px}
.dv-knopki{display:flex;flex-wrap:wrap;gap:6px}
.dv-tabl{overflow:auto;flex:1;min-height:0}
.dv-tabl table{width:100%;border-collapse:collapse}
.dv-tabl th{position:sticky;top:0;background:#f4f6f8;text-align:left;font-size:12px;color:#66727e;padding:6px 8px;font-weight:600}
.dv-tabl td{padding:7px 8px;border-top:1px solid #edf0f2;vertical-align:top;cursor:pointer}
.dv-tabl td:first-child{font-weight:700;color:#2f5d8a;width:32px;text-align:center}
.dv-tabl td .dv-opis{color:#55606b;font-size:12.5px;margin-top:2px}
.dv-tabl tr:hover td{background:#f6f9fb}
.dv-tabl tr.akt td{background:#fdf0e5}
.dv-podskaz{position:absolute;left:10px;bottom:8px;font-size:12px;color:#5d6873;background:rgba(255,255,255,.7);padding:2px 8px;border-radius:10px;pointer-events:none}
@media (max-width:760px){.dv{flex-direction:column}.dv-scena{flex:none;height:58%}.dv-panel{width:auto;flex:1;border-left:0;border-top:1px solid #dde3e8;overflow:auto}.dv-tabl{flex:none;overflow:visible}.dv-podskaz{display:none}}
`;

function vstavitStil(dok) {
  if (dok.getElementById('dv-stil')) return;
  const s = dok.createElement('style');
  s.id = 'dv-stil';
  s.textContent = STIL;
  dok.head.appendChild(s);
}

function el(teg, klass, tekst) {
  const e = document.createElement(teg);
  if (klass) e.className = klass;
  if (tekst != null) e.textContent = tekst;
  return e;
}

// ---------- Просмотрщик ----------

export function sozdatProsmotr(koren, model, opts = {}) {
  const oshibki = proverit(model);
  if (oshibki.length) throw new Error('Описание модели с ошибками:\n' + oshibki.join('\n'));
  vstavitStil(document);
  koren.innerHTML = '';
  const obolochka = el('div', 'dv');
  const scenaEl = el('div', 'dv-scena');
  const sloy = el('div', 'dv-sloy');
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  sloy.appendChild(svg);
  scenaEl.appendChild(sloy);
  scenaEl.appendChild(el('div', 'dv-podskaz', 'Крутить — мышью, приблизить — колёсиком'));
  obolochka.appendChild(scenaEl);
  koren.appendChild(obolochka);

  // Сцена, камера, свет.
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: !!opts.snimki });
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  scenaEl.insertBefore(renderer.domElement, sloy);
  const scena = new THREE.Scene();
  const kamera = new THREE.PerspectiveCamera(40, 1, 0.05, 500);
  const upr = new OrbitControls(kamera, renderer.domElement);
  upr.enableDamping = true;
  // Модель всегда в центре: сдвигать сцену нельзя, вращение и приближение — вокруг модели.
  upr.enablePan = false;
  upr.dampingFactor = 0.08;
  scena.add(new THREE.HemisphereLight(0xffffff, 0x9aa5b1, 1.6));
  const solnce = new THREE.DirectionalLight(0xffffff, 1.9);
  solnce.position.set(6, 12, 8);
  scena.add(solnce);
  const kontr = new THREE.DirectionalLight(0xdfe8ff, 0.6);
  kontr.position.set(-8, 3, -6);
  scena.add(kontr);

  const modelKoren = new THREE.Group();
  scena.add(modelKoren);

  // Части по порядку «сначала родители».
  const poId = new Map(model.parts.map((p) => [p.id, p]));
  const poryadok = [];
  const gotovo = new Set();
  const dobavit = (p) => {
    if (gotovo.has(p.id)) return;
    if (p.parent != null) dobavit(poId.get(p.parent));
    gotovo.add(p.id);
    poryadok.push(p);
  };
  model.parts.forEach(dobavit);

  const uzly = new Map();
  const vseMeshi = [];
  const deformiruemye = [];
  for (const p of poryadok) {
    const roditel = p.parent != null ? uzly.get(p.parent).obj : modelKoren;
    const obj = new THREE.Group();
    obj.name = p.id;
    if (p.rotation) obj.rotation.set(p.rotation[0] * DEG, p.rotation[1] * DEG, p.rotation[2] * DEG);
    if (p.scale) obj.scale.set(...p.scale);
    roditel.add(obj);
    roditel.updateMatrixWorld(true);
    obj.position.copy(roditel.worldToLocal(v3(p.position)));
    obj.updateMatrixWorld(true);
    const kVLokalnye = (v) => obj.worldToLocal(v.clone());
    const kVRoditelskie = (v) => roditel.worldToLocal(v.clone());
    const roditelQ = new THREE.Quaternion();
    roditel.getWorldQuaternion(roditelQ);
    const napravlenieVRoditele = (d) => v3(d).normalize().applyQuaternion(roditelQ.clone().invert());

    const f = p.shape || { type: 'group' };
    const forma = postroitFormu(f, kVLokalnye);
    const material = new THREE.MeshStandardMaterial({
      color: p.color ?? '#9aa7b4',
      roughness: 0.72,
      metalness: 0.04,
      side: ['kupol', 'wing', 'lathe'].includes(f.type) ? THREE.DoubleSide : THREE.FrontSide,
      vertexColors: !!forma.vertexColors,
    });
    if (forma.vertexColors) material.color.set('#ffffff');
    const meshi = [];
    const sdelatMeshi = (geometrii, mat) => {
      for (const g of geometrii) {
        const m = new THREE.Mesh(g, mat);
        m.userData.chast = p.id;
        obj.add(m);
        meshi.push(m);
        vseMeshi.push(m);
      }
    };
    sdelatMeshi(forma.geometrii, material);
    for (const d of forma.dop || []) {
      const dm = material.clone();
      dm.color.set(d.color);
      sdelatMeshi(d.geometrii, dm);
    }

    // Якоря: от формы (вершины сетки или точки) и заданные в описании.
    const yakorya = {};
    for (const [imya, spisok] of Object.entries(forma.yakorya || {})) {
      yakorya[imya] = spisok.map((y) => (y.index != null ? { mesh: meshi[0], index: y.index } : { obj, local: y.local }));
    }
    for (const [imya, tochki] of Object.entries(p.anchors || {})) {
      yakorya[imya] = tochki.map((t) => ({ obj, local: kVLokalnye(v3(t)) }));
    }

    if (forma.deform && meshi[0]) {
      const g = meshi[0].geometry;
      g.computeBoundingBox();
      const d = {
        mesh: meshi[0],
        baza: g.attributes.position.array.slice(),
        normali: g.attributes.normal.array.slice(),
        ves: g.attributes.ves ? g.attributes.ves.array : null,
        box: g.boundingBox.clone(),
        sdvig: new Float32Array(g.attributes.position.array.length),
        bylo: false,
      };
      deformiruemye.push(d);
      meshi[0].userData.deform = d;
    }

    // Точка для номера.
    let metka = null;
    if (p.label) metka = kVLokalnye(v3(p.label));
    else if (meshi.length) {
      const b = new THREE.Box3();
      for (const m of meshi) { m.geometry.computeBoundingBox(); b.union(m.geometry.boundingBox); }
      metka = b.getCenter(new THREE.Vector3());
    } else metka = new THREE.Vector3();

    const vz = p.explode || { dir: [0, 1, 0], dist: 0 };
    uzly.set(p.id, {
      p, obj, meshi, material, yakorya, metka,
      bazaPos: obj.position.clone(),
      bazaQ: obj.quaternion.clone(),
      bazaS: obj.scale.clone(),
      vzryv: napravlenieVRoditele(vz.dir).multiplyScalar(vz.dist || 0),
      kVRoditelskie,
      napravlenieVRoditele,
      linii: null,
    });
  }

  // Стропы: концы привязаны к якорям других деталей, линия тянется каждый кадр.
  const yakorTochki = (ssylka) => {
    if (Array.isArray(ssylka)) return ssylka.flatMap(yakorTochki);
    const [id, imya] = String(ssylka).split(':');
    const u = uzly.get(id);
    if (!u) return [];
    if (imya && u.yakorya[imya]) return u.yakorya[imya];
    return [{ obj: u.obj, local: imya ? new THREE.Vector3() : u.metka.clone() }];
  };
  const tmp = new THREE.Vector3();
  const mirovaya = (y, cel) => {
    if (y.mesh) {
      const a = y.mesh.geometry.attributes.position;
      cel.set(a.getX(y.index), a.getY(y.index), a.getZ(y.index));
      return y.mesh.localToWorld(cel);
    }
    return y.obj.localToWorld(cel.copy(y.local));
  };
  modelKoren.updateMatrixWorld(true);
  for (const u of uzly.values()) {
    if (u.p.shape?.type !== 'lines') continue;
    const f = u.p.shape;
    const ot = yakorTochki(f.from);
    const k = yakorTochki(f.to);
    const pary = [];
    if (f.map === 'paired') ot.forEach((a, i) => pary.push([a, k[i % k.length]]));
    else {
      const b = new THREE.Vector3();
      for (const a of ot) {
        mirovaya(a, tmp);
        let luch = k[0];
        let min = Infinity;
        for (const c of k) {
          const d = mirovaya(c, b).distanceTo(tmp);
          if (d < min) { min = d; luch = c; }
        }
        pary.push([a, luch]);
      }
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(new Float32Array(pary.length * 6), 3));
    const mat = new THREE.LineBasicMaterial({ color: u.p.color ?? '#555555', transparent: true, opacity: 0.9 });
    const l = new THREE.LineSegments(g, mat);
    l.userData.chast = u.p.id;
    l.frustumCulled = false;
    modelKoren.add(l);
    vseMeshi.push(l);
    u.linii = { obj: l, pary };
    u.material = mat;
  }
  const obnovitLinii = () => {
    const a = new THREE.Vector3();
    const b = new THREE.Vector3();
    for (const u of uzly.values()) {
      if (!u.linii) continue;
      const pos = u.linii.obj.geometry.attributes.position;
      u.linii.pary.forEach(([p, q], i) => {
        mirovaya(p, a);
        mirovaya(q, b);
        pos.setXYZ(i * 2, a.x, a.y, a.z);
        pos.setXYZ(i * 2 + 1, b.x, b.y, b.z);
      });
      pos.needsUpdate = true;
    }
  };

  // ---------- Анимации ----------
  const animacii = (model.animations || []).map((a) => {
    const vid = ANIMACII[a.type].control;
    const par = a.params || {};
    const u = uzly.get(a.target);
    const st = {
      a, u, par, vid,
      vkl: !!a.autoplay,
      ves: a.autoplay ? 1 : 0,
      znach: vid === 'polzunok' ? (par.default ?? 1) : vid === 'polzunok-pm' ? 0 : 0,
      tek: 0,
      faza: 0,
      yaw: 0,
    };
    st.tek = st.znach;
    if (par.pivot) st.pivot = u.kVRoditelskie(v3(par.pivot));
    if (a.type === 'unfold') {
      st.otMasht = v3(par.fromScale, [0.2, 0.4, 0.2]);
      st.otSdvig = par.fromOffset ? u.napravlenieVRoditele(par.fromOffset).multiplyScalar(v3(par.fromOffset).length()) : new THREE.Vector3();
    }
    if (a.type === 'control') {
      st.tyagi = (par.pulls || []).map((t) => ({
        u: uzly.get(t.part),
        sdvig: uzly.get(t.part) ? uzly.get(t.part).napravlenieVRoditele(t.offset ?? [0, -0.3, 0]).multiplyScalar(v3(t.offset, [0, -0.3, 0]).length()) : null,
        storona: t.side === 'left' ? -1 : 1,
      })).filter((t) => t.u);
      st.zakrylok = par.flap ? { u: uzly.get(par.flap.part), velichina: par.flap.amount ?? 0.5 } : null;
    }
    if (a.type === 'descent') st.potok = sozdatPotok(par);
    return st;
  });

  function sozdatPotok(par) {
    const n = par.streaks ?? 70;
    const g = new THREE.BufferGeometry();
    const pos = new Float32Array(n * 6);
    g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    const mat = new THREE.LineBasicMaterial({ color: '#ffffff', transparent: true, opacity: 0 });
    const l = new THREE.LineSegments(g, mat);
    l.frustumCulled = false;
    scena.add(l);
    const box = new THREE.Box3().setFromObject(modelKoren);
    const c = box.getCenter(new THREE.Vector3());
    const r = Math.max(2, box.getSize(new THREE.Vector3()).length() * 0.6);
    const tochki = [];
    for (let i = 0; i < n; i++) {
      const ug = Math.random() * Math.PI * 2;
      const rr = r * (0.5 + Math.random() * 0.7);
      tochki.push({ x: c.x + Math.cos(ug) * rr, z: c.z + Math.sin(ug) * rr, y: c.y - r + Math.random() * 2 * r, d: 0.3 + Math.random() * 0.6 });
    }
    return { l, mat, tochki, c, r };
  }

  const qTmp = new THREE.Quaternion();
  const osTmp = new THREE.Vector3();
  const povernutVokrug = (u, os, ugol, pivot) => {
    qTmp.setFromAxisAngle(osTmp.copy(os).normalize(), ugol);
    if (pivot) u.obj.position.sub(pivot).applyQuaternion(qTmp).add(pivot);
    u.obj.quaternion.premultiply(qTmp);
  };

  function primenitAnimacii(t, dt) {
    for (const d of deformiruemye) d.sdvig.fill(0);
    let estDeform = false;
    for (const s of animacii) {
      const cel = s.vkl ? 1 : 0;
      s.ves += (cel - s.ves) * Math.min(1, dt * 2.5);
      if (Math.abs(s.ves - cel) < 0.002) s.ves = cel;
      s.tek += (s.znach - s.tek) * Math.min(1, dt * 4);
      const { u, par } = s;
      const w = s.ves;
      switch (s.a.type) {
        case 'swing': {
          if (w <= 0) break;
          const ugol = w * (par.amplitude ?? 10) * DEG * Math.sin((2 * Math.PI * t) / (par.period ?? 4));
          povernutVokrug(u, v3(par.axis, [0, 0, 1]), ugol, s.pivot);
          break;
        }
        case 'rotate': {
          s.faza += w * (par.speed ?? 90) * DEG * dt;
          if (s.faza === 0) break;
          const os = v3(par.axis, [0, 1, 0]);
          if (s.pivot) povernutVokrug(u, os, s.faza, s.pivot);
          else u.obj.quaternion.multiply(qTmp.setFromAxisAngle(os.normalize(), s.faza));
          break;
        }
        case 'breathe': {
          if (w <= 0) break;
          const d = u.meshi[0]?.userData.deform;
          if (!d) break;
          estDeform = true;
          const amp = w * (par.amplitude ?? 0.06);
          const ch = par.speed ?? 0.6;
          const dl = par.wavelength ?? 3;
          const os = { x: 0, y: 1, z: 2 }[par.axis ?? 'x'];
          for (let i = 0; i < d.sdvig.length / 3; i++) {
            const vs = d.ves ? d.ves[i] : 1;
            if (!vs) continue;
            const k = amp * vs * Math.sin(2 * Math.PI * (ch * t - d.baza[i * 3 + os] / dl));
            d.sdvig[i * 3] += d.normali[i * 3] * k;
            d.sdvig[i * 3 + 1] += d.normali[i * 3 + 1] * k;
            d.sdvig[i * 3 + 2] += d.normali[i * 3 + 2] * k;
          }
          break;
        }
        case 'unfold': {
          const v = plavno(zazhat(s.tek, 0, 1));
          if (v >= 1) break;
          u.obj.scale.multiply(new THREE.Vector3(1, 1, 1).lerp(s.otMasht, 1 - v));
          u.obj.position.addScaledVector(s.otSdvig, 1 - v);
          break;
        }
        case 'control': {
          const v = zazhat(s.tek, -1, 1);
          s.yaw += -v * (par.yawSpeed ?? 25) * DEG * dt;
          if (s.yaw) u.obj.quaternion.premultiply(qTmp.setFromAxisAngle(new THREE.Vector3(0, 1, 0), s.yaw));
          if (v) {
            const vpered = new THREE.Vector3(0, 0, 1).applyQuaternion(qTmp.setFromAxisAngle(new THREE.Vector3(0, 1, 0), s.yaw));
            povernutVokrug(u, vpered, v * (par.bank ?? 15) * DEG, s.pivot);
          }
          for (const tg of s.tyagi) {
            const k = Math.max(0, v * tg.storona);
            if (k) tg.u.obj.position.addScaledVector(tg.sdvig, k);
          }
          if (s.zakrylok && s.zakrylok.u && v) {
            const d = s.zakrylok.u.meshi[0]?.userData.deform;
            if (d) {
              estDeform = true;
              const b = d.box;
              const polX = Math.max(Math.abs(b.min.x), Math.abs(b.max.x)) || 1;
              const polZ = (b.max.z - b.min.z) / 2 || 1;
              const cz = (b.max.z + b.min.z) / 2;
              for (let i = 0; i < d.sdvig.length / 3; i++) {
                const x = d.baza[i * 3] / polX;
                const z = (cz - d.baza[i * 3 + 2]) / polZ;
                const storona = Math.max(0, -x * Math.sign(v)); // правая сторона — минус X
                const hvost = Math.max(0, z) ** 2;
                d.sdvig[i * 3 + 1] -= s.zakrylok.velichina * Math.abs(v) * storona * hvost;
              }
            }
          }
          break;
        }
        case 'jitter': {
          if (w <= 0) break;
          const a = w * (par.amplitude ?? 1.2) * DEG;
          const sp = par.speed ?? 1;
          const sh = (k) => Math.sin(t * 7.3 * sp + k) * 0.5 + Math.sin(t * 13.1 * sp + 2 * k) * 0.3 + Math.sin(t * 3.7 * sp + 3 * k) * 0.2;
          u.obj.quaternion.multiply(qTmp.setFromEuler(new THREE.Euler(a * sh(1), a * 0.5 * sh(4), a * sh(2))));
          const m = w * (par.offset ?? 0.015);
          u.obj.position.x += m * sh(5);
          u.obj.position.y += m * sh(6);
          break;
        }
        case 'descent': {
          const p = s.potok;
          p.mat.opacity = 0.55 * w;
          p.l.visible = w > 0;
          if (w <= 0) break;
          const v = par.speed ?? 3;
          const pos = p.l.geometry.attributes.position;
          p.tochki.forEach((q, i) => {
            q.y += v * dt * w;
            if (q.y > p.c.y + p.r) q.y -= 2 * p.r;
            pos.setXYZ(i * 2, q.x, q.y, q.z);
            pos.setXYZ(i * 2 + 1, q.x, q.y + q.d, q.z);
          });
          pos.needsUpdate = true;
          u.obj.position.y += w * (par.bob ?? 0.08) * Math.sin(t * 0.9);
          break;
        }
      }
    }
    for (const d of deformiruemye) {
      if (!estDeform && !d.bylo) continue;
      const a = d.mesh.geometry.attributes.position;
      for (let i = 0; i < a.array.length; i++) a.array[i] = d.baza[i] + d.sdvig[i];
      a.needsUpdate = true;
      d.mesh.geometry.computeVertexNormals();
      d.bylo = estDeform;
    }
  }

  // ---------- Взрыв-схема ----------
  let vzryv = 0;
  let perehod = null;
  const ustanovitVzryv = (v) => { vzryv = zazhat(v, 0, 1); perehod = null; };
  const plavnoVzryv = (cel, dlit = 1.2) => { perehod = { ot: vzryv, k: cel, t0: performance.now(), dlit }; };

  const sbrositPozy = () => {
    for (const u of uzly.values()) {
      u.obj.position.copy(u.bazaPos).addScaledVector(u.vzryv, vzryv);
      u.obj.quaternion.copy(u.bazaQ);
      u.obj.scale.copy(u.bazaS);
    }
  };

  // ---------- Камера ----------
  // Камера всегда смотрит в середину модели и следит за ней при анимациях и разборке.
  // Описание задаёт только сторону, с которой смотреть; расстояние подбирается, чтобы
  // модель целиком помещалась в кадр.
  const ramka = new THREE.Box3().setFromObject(modelKoren);
  const centrModeli = ramka.getCenter(new THREE.Vector3());
  const radiusModeli = Math.max(0.05, ramka.getBoundingSphere(new THREE.Sphere()).radius);
  upr.minDistance = radiusModeli * 0.3;
  upr.maxDistance = radiusModeli * 12;
  const vpisat = (napr) => {
    const vfov = kamera.fov * DEG;
    const hfov = 2 * Math.atan(Math.tan(vfov / 2) * kamera.aspect);
    return (radiusModeli / Math.sin(Math.min(vfov, hfov) / 2)) * 1.05;
  };
  const vidPoUmolch = () => {
    const vid = model.view || {};
    const napr = vid.camera ? v3(vid.camera).sub(vid.target ? v3(vid.target) : centrModeli) : new THREE.Vector3(0.55, 0.25, 0.8);
    if (napr.lengthSq() < 1e-9) napr.set(0.55, 0.25, 0.8);
    upr.target.copy(tekCentr());
    kamera.position.copy(upr.target).addScaledVector(napr.normalize(), vpisat());
    upr.update();
  };
  const tmpRamka = new THREE.Box3();
  const tekCentr = () => {
    tmpRamka.setFromObject(modelKoren);
    return tmpRamka.isEmpty() ? centrModeli.clone() : tmpRamka.getCenter(new THREE.Vector3());
  };
  // Каждые несколько кадров плавно подводим середину кадра к середине модели.
  let schetSlezhki = 0;
  const sledit = () => {
    if (++schetSlezhki % 4) return;
    const sdvig = tekCentr().sub(upr.target);
    if (sdvig.lengthSq() < 1e-8) return;
    sdvig.multiplyScalar(0.35);
    upr.target.add(sdvig);
    kamera.position.add(sdvig);
  };
  // Первый вид — когда известен размер окна: от него зависит, поместится ли модель.
  let nuzhenVid = true;
  const pervyyVid = () => {
    nuzhenVid = false;
    if (opts.kamera) {
      // Модель обновилась: сторона и расстояние прежние, середина — новая
      const napr = new THREE.Vector3().fromArray(opts.kamera.poz).sub(new THREE.Vector3().fromArray(opts.kamera.cel));
      upr.target.copy(tekCentr());
      const dist = zazhat(napr.length(), upr.minDistance, upr.maxDistance);
      kamera.position.copy(upr.target).addScaledVector(napr.normalize(), dist);
      upr.update();
    } else vidPoUmolch();
  };

  // ---------- Номера и подсветка ----------
  const detali = spisokDetaley(model);
  const metki = new Map();
  const linii = new Map();
  for (const d of detali) {
    const m = el('div', 'dv-num', String(d.num));
    m.title = d.name;
    m.addEventListener('click', (e) => { e.stopPropagation(); vybrat(d.id, 'metka'); });
    sloy.appendChild(m);
    metki.set(d.id, m);
    const ln = document.createElementNS('http://www.w3.org/2000/svg', 'line');
    ln.setAttribute('stroke', '#2f5d8a');
    ln.setAttribute('stroke-width', '1.3');
    svg.appendChild(ln);
    linii.set(d.id, ln);
  }
  let nomeraVidny = opts.nomera ?? true;
  const pokazatNomera = (da) => { nomeraVidny = da; sloy.style.display = da ? '' : 'none'; };
  pokazatNomera(nomeraVidny);

  let vybrannaya = null;
  const slushateli = [];
  const SVET = new THREE.Color('#e8731c');
  function podsvetit(id, vkl) {
    const u = uzly.get(id);
    if (!u) return;
    // Подсвечиваем деталь вместе с вложенными частями без своего номера.
    const vse = [u];
    for (let i = 0; i < vse.length; i++) {
      for (const d of uzly.values()) if (d.p.parent === vse[i].p.id && d.p.num == null) vse.push(d);
    }
    const mats = new Set(vse.flatMap((x) => [x.material, ...x.meshi.map((m) => m.material)]));
    for (const m of mats) {
      if (!m) continue;
      if (m.isLineBasicMaterial) {
        if (vkl) { m.userData.bylo = m.color.getHex(); m.color.copy(SVET); }
        else if (m.userData.bylo != null) m.color.setHex(m.userData.bylo);
      } else if (m.emissive) {
        m.emissive.copy(vkl ? SVET : new THREE.Color(0));
        m.emissiveIntensity = vkl ? 0.45 : 0;
      }
    }
  }
  function vybrat(id, otkuda) {
    if (vybrannaya) {
      podsvetit(vybrannaya, false);
      metki.get(vybrannaya)?.classList.remove('akt');
      stroki.get(vybrannaya)?.classList.remove('akt');
    }
    vybrannaya = id && uzly.has(id) ? id : null;
    if (vybrannaya) {
      podsvetit(vybrannaya, true);
      metki.get(vybrannaya)?.classList.add('akt');
      const str = stroki.get(vybrannaya);
      if (str) {
        str.classList.add('akt');
        if (otkuda !== 'stroka') str.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
      }
    }
    for (const f of slushateli) f(vybrannaya, otkuda);
  }

  // Клик по детали в сцене.
  const luch = new THREE.Raycaster();
  luch.params.Line.threshold = 0.06;
  let nazhato = null;
  renderer.domElement.addEventListener('pointerdown', (e) => { nazhato = [e.clientX, e.clientY]; });
  renderer.domElement.addEventListener('pointerup', (e) => {
    if (!nazhato || Math.hypot(e.clientX - nazhato[0], e.clientY - nazhato[1]) > 5) return;
    const r = renderer.domElement.getBoundingClientRect();
    luch.setFromCamera(new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1), kamera);
    const popal = luch.intersectObjects(vseMeshi, false).find((h) => h.object.visible);
    let id = popal ? popal.object.userData.chast : null;
    // Если у детали нет номера — подсвечиваем ближайшего пронумерованного родителя.
    while (id && poId.get(id).num == null && poId.get(id).parent != null) id = poId.get(id).parent;
    if (id && poId.get(id).num == null) id = null;
    vybrat(id, 'scena');
  });

  // ---------- Панель ----------
  const stroki = new Map();
  const knopkiAnim = new Map();
  let panel = null;
  if (opts.panel !== false) {
    panel = el('div', 'dv-panel');
    const u = el('div', 'dv-upr');
    u.appendChild(el('h1', null, model.name));
    if (model.scale?.text) u.appendChild(el('div', 'dv-masht', 'Масштаб: ' + model.scale.text));

    const ryadV = el('div', 'dv-ryad');
    ryadV.appendChild(el('label', null, 'Разборка'));
    const polzV = el('input');
    polzV.type = 'range'; polzV.min = 0; polzV.max = 1; polzV.step = 0.01; polzV.value = 0;
    polzV.setAttribute('aria-label', 'Взрыв-схема');
    polzV.addEventListener('input', () => ustanovitVzryv(+polzV.value));
    ryadV.appendChild(polzV);
    u.appendChild(ryadV);
    const ryadK = el('div', 'dv-ryad');
    const bSobr = el('button', null, 'Собрать');
    const bRazb = el('button', null, 'Разобрать');
    bSobr.onclick = () => plavnoVzryv(0);
    bRazb.onclick = () => plavnoVzryv(1);
    const bNom = el('button', nomeraVidny ? 'vkl' : '', 'Номера');
    bNom.onclick = () => { pokazatNomera(!nomeraVidny); bNom.classList.toggle('vkl', nomeraVidny); };
    const bVid = el('button', null, 'Исходный вид');
    bVid.onclick = vidPoUmolch;
    ryadK.append(bSobr, bRazb, bNom, bVid);
    u.appendChild(ryadK);
    polzV._obnovit = () => { polzV.value = vzryv; };

    if (animacii.length) {
      u.appendChild(el('div', 'dv-zag', 'Анимации'));
      const knopki = el('div', 'dv-knopki');
      for (const s of animacii) {
        if (s.vid !== 'knopka') continue;
        const b = el('button', s.vkl ? 'vkl' : '', s.a.name);
        b.onclick = () => vklyuchit(s.a.id, !s.vkl);
        knopki.appendChild(b);
        knopkiAnim.set(s.a.id, b);
      }
      if (knopki.children.length) u.appendChild(knopki);
      for (const s of animacii) {
        if (s.vid === 'knopka') continue;
        const r = el('div', 'dv-ryad');
        r.appendChild(el('label', null, s.a.name));
        const p = el('input');
        p.type = 'range';
        p.min = s.vid === 'polzunok-pm' ? -1 : 0; p.max = 1; p.step = 0.01; p.value = s.znach;
        p.setAttribute('aria-label', s.a.name);
        p.addEventListener('input', () => { s.znach = +p.value; });
        if (s.vid === 'polzunok-pm') {
          // Отпустили — плавно в середину, как отпущенные клеванты.
          p.addEventListener('change', () => { if (s.a.params?.returnToCenter !== false) { s.znach = 0; p.value = 0; } });
        }
        r.appendChild(p);
        u.appendChild(r);
        knopkiAnim.set(s.a.id, p);
      }
    }
    panel.appendChild(u);

    const tabl = el('div', 'dv-tabl');
    const t = el('table');
    const thead = el('thead');
    const hr = el('tr');
    hr.append(el('th', null, '№'), el('th', null, 'Деталь'));
    thead.appendChild(hr);
    t.appendChild(thead);
    const tb = el('tbody');
    for (const d of detali) {
      const tr = el('tr');
      tr.dataset.id = d.id;
      const td2 = el('td');
      td2.appendChild(el('div', null, d.name));
      if (d.desc) td2.appendChild(el('div', 'dv-opis', d.desc));
      tr.append(el('td', null, String(d.num)), td2);
      tr.onclick = () => vybrat(vybrannaya === d.id ? null : d.id, 'stroka');
      tb.appendChild(tr);
      stroki.set(d.id, tr);
    }
    t.appendChild(tb);
    tabl.appendChild(t);
    panel.appendChild(tabl);
    obolochka.appendChild(panel);
    panel._polzV = polzV;
  }

  function vklyuchit(id, da) {
    const s = animacii.find((x) => x.a.id === id);
    if (!s) return;
    if (s.vid === 'knopka') {
      s.vkl = da;
      knopkiAnim.get(id)?.classList.toggle('vkl', da);
    }
  }
  function znachenie(id, v) {
    const s = animacii.find((x) => x.a.id === id);
    if (!s) return;
    s.znach = v;
    const p = knopkiAnim.get(id);
    if (p && p.type === 'range') p.value = v;
  }

  // ---------- Кадр ----------
  const ekran = new THREE.Vector3();
  const centrEkr = new THREE.Vector3();
  function obnovitMetki(w, h) {
    if (!nomeraVidny || !metki.size) return;
    centrEkr.copy(upr.target).project(kamera);
    const cx = (centrEkr.x * 0.5 + 0.5) * w;
    const cy = (-centrEkr.y * 0.5 + 0.5) * h;
    const tochkiMetok = [];
    for (const [id, m] of metki) {
      const u = uzly.get(id);
      if (u.linii && u.linii.pary.length) {
        const f = u.p.shape;
        const n = u.linii.pary.length;
        const [a, b] = u.linii.pary[zazhat(f.labelIndex ?? Math.floor(n / 3), 0, n - 1)];
        const pa = mirovaya(a, new THREE.Vector3());
        const pb = mirovaya(b, new THREE.Vector3());
        ekran.copy(pa).lerp(pb, f.labelAt ?? 0.55);
      } else ekran.copy(u.metka).applyMatrix4(u.obj.matrixWorld);
      ekran.project(kamera);
      const ln = linii.get(id);
      if (ekran.z > 1) { m.style.display = 'none'; ln.style.display = 'none'; continue; }
      m.style.display = ''; ln.style.display = '';
      const x = (ekran.x * 0.5 + 0.5) * w;
      const y = (-ekran.y * 0.5 + 0.5) * h;
      let dx = x - cx;
      let dy = y - cy;
      const dl = Math.hypot(dx, dy) || 1;
      dx /= dl; dy /= dl;
      if (dl < 2) { dx = 0.7; dy = -0.7; }
      tochkiMetok.push({ m, ln, x, y, mx: x + dx * 34, my: y + dy * 34 });
    }
    // Раздвигаем кружки, которые налезают друг на друга.
    for (let shag = 0; shag < 6; shag++) {
      for (let i = 0; i < tochkiMetok.length; i++) {
        for (let j = i + 1; j < tochkiMetok.length; j++) {
          const a = tochkiMetok[i];
          const b = tochkiMetok[j];
          let ddx = b.mx - a.mx;
          let ddy = b.my - a.my;
          const d = Math.hypot(ddx, ddy);
          if (d >= 27) continue;
          if (d < 0.01) { ddx = 1; ddy = 0; } else { ddx /= d; ddy /= d; }
          const k = (27 - d) / 2;
          a.mx -= ddx * k; a.my -= ddy * k;
          b.mx += ddx * k; b.my += ddy * k;
        }
      }
    }
    for (const t of tochkiMetok) {
      t.m.style.left = t.mx + 'px';
      t.m.style.top = t.my + 'px';
      t.ln.setAttribute('x1', t.x); t.ln.setAttribute('y1', t.y);
      t.ln.setAttribute('x2', t.mx); t.ln.setAttribute('y2', t.my);
    }
  }

  let shirina = 0;
  let vysota = 0;
  const razmer = () => {
    const w = scenaEl.clientWidth || 1;
    const h = scenaEl.clientHeight || 1;
    if (w === shirina && h === vysota) return;
    shirina = w; vysota = h;
    renderer.setSize(w, h, false);
    kamera.aspect = w / h;
    kamera.updateProjectionMatrix();
  };
  const ro = new ResizeObserver(razmer);
  ro.observe(scenaEl);

  const chasy = new THREE.Timer();
  let rabotaet = true;
  let vremya = 0;
  function kadr(ms) {
    if (!rabotaet) return;
    requestAnimationFrame(kadr);
    chasy.update(ms);
    const dt = Math.min(0.05, chasy.getDelta());
    vremya += dt;
    if (perehod) {
      const k = zazhat((performance.now() - perehod.t0) / (perehod.dlit * 1000), 0, 1);
      vzryv = perehod.ot + (perehod.k - perehod.ot) * plavno(k);
      if (k >= 1) perehod = null;
      panel?._polzV._obnovit();
    }
    razmer();
    if (nuzhenVid) pervyyVid();
    sbrositPozy();
    primenitAnimacii(vremya, dt);
    modelKoren.updateMatrixWorld(true);
    obnovitLinii();
    sledit();
    upr.update();
    renderer.render(scena, kamera);
    obnovitMetki(shirina, vysota);
  }
  requestAnimationFrame(kadr);

  return {
    model,
    kanva: renderer.domElement,
    kamera,
    scena,
    modelKoren,
    vybrat,
    naVybor: (f) => slushateli.push(f),
    ustanovitVzryv: (v) => { ustanovitVzryv(v); panel?._polzV._obnovit(); },
    plavnoVzryv,
    pokazatNomera,
    vklyuchit,
    znachenie,
    vidPoUmolch,
    // Где деталь на экране (в пикселях холста) — для автоматических проверок.
    ekrannayaTochka(id) {
      const u = uzly.get(id);
      if (!u || !u.meshi.length) return null;
      // Берём вершину из середины сетки — она точно лежит на поверхности детали.
      const a = u.meshi[0].geometry.attributes.position;
      const i = Math.floor(a.count / 2);
      const p = new THREE.Vector3(a.getX(i), a.getY(i), a.getZ(i)).applyMatrix4(u.meshi[0].matrixWorld).project(kamera);
      return { x: (p.x * 0.5 + 0.5) * shirina, y: (-p.y * 0.5 + 0.5) * vysota };
    },
    avtoPovorot(da, skorost = 1.2) { upr.autoRotate = da; upr.autoRotateSpeed = skorost; },
    kameraSostoyanie: () => ({ poz: kamera.position.toArray(), cel: upr.target.toArray() }),
    // Отрисовать кадр с номерами прямо на картинке — для видео и снимков.
    narisovatKadr(ctx, w, h) {
      ctx.drawImage(renderer.domElement, 0, 0, w, h);
      if (!nomeraVidny) return;
      const sx = w / shirina;
      const sy = h / vysota;
      ctx.save();
      for (const [id, m] of metki) {
        if (m.style.display === 'none') continue;
        const ln = linii.get(id);
        ctx.strokeStyle = '#2f5d8a';
        ctx.lineWidth = 1.3 * sx;
        ctx.beginPath();
        ctx.moveTo(+ln.getAttribute('x1') * sx, +ln.getAttribute('y1') * sy);
        ctx.lineTo(+ln.getAttribute('x2') * sx, +ln.getAttribute('y2') * sy);
        ctx.stroke();
        const x = parseFloat(m.style.left) * sx;
        const y = parseFloat(m.style.top) * sy;
        const akt = id === vybrannaya;
        ctx.fillStyle = akt ? '#e8731c' : '#ffffff';
        ctx.strokeStyle = akt ? '#e8731c' : '#2f5d8a';
        ctx.lineWidth = 2 * sx;
        ctx.beginPath();
        ctx.arc(x, y, 11 * sx, 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();
        ctx.fillStyle = akt ? '#ffffff' : '#2f5d8a';
        ctx.font = `bold ${12 * sx}px system-ui, sans-serif`;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(m.textContent, x, y + 0.5 * sx);
      }
      ctx.restore();
    },
    unichtozhit() {
      rabotaet = false;
      ro.disconnect();
      upr.dispose();
      renderer.dispose();
      koren.innerHTML = '';
    },
  };
}
