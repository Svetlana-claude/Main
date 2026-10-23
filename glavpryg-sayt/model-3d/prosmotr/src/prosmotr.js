// Тяжёлая часть, которая грузится только по кнопке: свой маленький показ на WebGL2.
// three.js здесь не нужен — модели хватает освещения, вращения и выбора детали,
// а three.js весит 155 КБ сжатым; этот файл вместе с распаковщиком meshopt — ~10 КБ.
// Кадр рисуется только по надобности (повернули, выбрали деталь, сменился размер):
// в покое показ не тратит ни процессор, ни батарею.

import { MeshoptDecoder } from 'meshoptimizer/meshopt_decoder.module.js';

const CEL = [0, 1.04, 0];
const NACHALO = { azimut: 0.42, polyar: 1.40, radius: 2.3 };
// ?vid=азимут,полярный,радиус — начальная камера для снимков превью (tools/oblozhka.py)
const VID = new URLSearchParams(location.search).get('vid')?.split(',').map(Number);
if (VID?.length === 3 && VID.every(Number.isFinite)) [NACHALO.azimut, NACHALO.polyar, NACHALO.radius] = VID;
const PODSVETKA = [0.95, 0.42, 0.1];
const bezDvizheniya = matchMedia('(prefers-reduced-motion: reduce)').matches;

// ---------- Матрицы 4×4 (по столбцам, как в WebGL) ----------
const umn = (a, b) => {
  const o = new Float32Array(16);
  for (let i = 0; i < 4; i++) for (let j = 0; j < 4; j++) {
    o[j * 4 + i] = a[i] * b[j * 4] + a[4 + i] * b[j * 4 + 1] + a[8 + i] * b[j * 4 + 2] + a[12 + i] * b[j * 4 + 3];
  }
  return o;
};
const perspektiva = (fov, asp, n, f) => {
  const t = 1 / Math.tan(fov / 2);
  return new Float32Array([t / asp, 0, 0, 0, 0, t, 0, 0, 0, 0, (f + n) / (n - f), -1, 0, 0, (2 * f * n) / (n - f), 0]);
};
const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const normir = (a) => { const d = Math.hypot(...a) || 1; return [a[0] / d, a[1] / d, a[2] / d]; };
const vzglyad = (oko, cel) => {
  const z = normir(sub(oko, cel)), x = normir(cross([0, 1, 0], z)), y = cross(z, x);
  return new Float32Array([x[0], y[0], z[0], 0, x[1], y[1], z[1], 0, x[2], y[2], z[2], 0,
    -dot(x, oko), -dot(y, oko), -dot(z, oko), 1]);
};
const trs = (u) => {
  if (u.matrix) return new Float32Array(u.matrix);
  const [x, y, z, w] = u.rotation ?? [0, 0, 0, 1], [sx, sy, sz] = u.scale ?? [1, 1, 1], t = u.translation ?? [0, 0, 0];
  return new Float32Array([
    (1 - 2 * (y * y + z * z)) * sx, 2 * (x * y + z * w) * sx, 2 * (x * z - y * w) * sx, 0,
    2 * (x * y - z * w) * sy, (1 - 2 * (x * x + z * z)) * sy, 2 * (y * z + x * w) * sy, 0,
    2 * (x * z + y * w) * sz, 2 * (y * z - x * w) * sz, (1 - 2 * (x * x + y * y)) * sz, 0,
    t[0], t[1], t[2], 1]);
};
const EDIN = trs({});

// ---------- Шейдеры ----------
const VERSH = `#version 300 es
layout(location=0) in vec3 aP; layout(location=1) in vec3 aN;
uniform mat4 uM, uVP; out vec3 vP, vN;
void main() { vec4 p = uM * vec4(aP, 1.0); vP = p.xyz; vN = mat3(uM) * aN; gl_Position = uVP * p; }`;

const OSN = `#version 300 es
precision highp float;
in vec3 vP, vN; uniform vec3 uCvet, uSvechenie, uOko; uniform vec2 uMR; out vec4 o;
const vec3 NEBO = vec3(1.0), ZEMLYA = vec3(0.33, 0.36, 0.43);
vec3 svet(vec3 n, vec3 v, vec3 l, vec3 c, float blesk, vec3 f0) {
  float d = max(dot(n, l), 0.0);
  float s = pow(max(dot(n, normalize(l + v)), 0.0), blesk) * (blesk + 8.0) / 25.0;
  return c * d * (uCvet * (1.0 - uMR.x) + f0 * s);
}
void main() {
  vec3 n = normalize(vN), v = normalize(uOko - vP);
  if (dot(n, v) < 0.0) n = -n;
  float blesk = exp2(10.0 * (1.0 - uMR.y) + 1.0);
  vec3 f0 = mix(vec3(0.04), uCvet, uMR.x);
  vec3 c = uCvet * (1.0 - uMR.x) * mix(ZEMLYA, NEBO, n.y * 0.5 + 0.5) * 0.75;
  c += svet(n, v, normalize(vec3(0.5, 1.0, 0.85)), vec3(1.55), blesk, f0);
  c += svet(n, v, normalize(vec3(-0.6, 0.4, -0.75)), vec3(0.55, 0.6, 0.72), blesk, f0);
  vec3 r = reflect(-v, n);
  c += f0 * mix(ZEMLYA, NEBO, smoothstep(-0.3, 0.6, r.y)) * (0.3 + 0.7 * uMR.x);
  c += uSvechenie;
  o = vec4(pow(c / (1.0 + c * 0.15), vec3(1.0 / 2.2)), 1.0);
}`;

// Служебный проход: номер детали и глубина — для выбора нажатием и перекрытия меток
const SLUZH = `#version 300 es
precision highp float; uniform float uId; out vec4 o;
void main() { float z = gl_FragCoord.z * 16777215.0;
  o = vec4(uId / 255.0, floor(z / 65536.0) / 255.0, mod(floor(z / 256.0), 256.0) / 255.0, mod(z, 256.0) / 255.0); }`;

function programma(gl, vs, fs) {
  const p = gl.createProgram();
  for (const [tip, kod] of [[gl.VERTEX_SHADER, vs], [gl.FRAGMENT_SHADER, fs]]) {
    const s = gl.createShader(tip);
    gl.shaderSource(s, kod);
    gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s));
    gl.attachShader(p, s);
  }
  gl.linkProgram(p);
  if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p));
  const u = {};
  for (let i = gl.getProgramParameter(p, gl.ACTIVE_UNIFORMS); i--;) {
    const imya = gl.getActiveUniform(p, i).name;
    u[imya] = gl.getUniformLocation(p, imya);
  }
  return { p, u };
}

// ---------- Загрузка GLB со сжатием meshopt и квантованием ----------
async function zagruzitGlb(gl, adres) {
  const [buf] = await Promise.all([fetch(adres).then((r) => {
    if (!r.ok) throw new Error(`${adres}: ${r.status}`);
    return r.arrayBuffer();
  }), MeshoptDecoder.ready]);
  const dv = new DataView(buf);
  const dlJson = dv.getUint32(12, true);
  const j = JSON.parse(new TextDecoder().decode(new Uint8Array(buf, 20, dlJson)));
  const bin = new Uint8Array(buf, 28 + dlJson, dv.getUint32(20 + dlJson, true));

  // Каждый вид буфера распаковывается один раз и уходит в видеопамять
  const vidy = j.bufferViews.map((bv) => {
    const m = bv.extensions?.EXT_meshopt_compression;
    let dannye;
    if (m) {
      dannye = new Uint8Array(m.count * m.byteStride);
      MeshoptDecoder.decodeGltfBuffer(dannye, m.count, m.byteStride,
        bin.subarray(m.byteOffset ?? 0, (m.byteOffset ?? 0) + m.byteLength), m.mode, m.filter);
    } else {
      dannye = bin.subarray(bv.byteOffset ?? 0, (bv.byteOffset ?? 0) + bv.byteLength);
    }
    const cel = bv.target ?? gl.ARRAY_BUFFER;
    const b = gl.createBuffer();
    gl.bindBuffer(cel, b);
    gl.bufferData(cel, dannye, gl.STATIC_DRAW);
    return { b, shag: bv.byteStride ?? 0 };
  });

  const RAZM = { SCALAR: 1, VEC2: 2, VEC3: 3, VEC4: 4 };
  const atribut = (nomer, i) => {
    const a = j.accessors[i], v = vidy[a.bufferView];
    gl.bindBuffer(gl.ARRAY_BUFFER, v.b);
    gl.enableVertexAttribArray(nomer);
    gl.vertexAttribPointer(nomer, RAZM[a.type], a.componentType, !!a.normalized, v.shag, a.byteOffset ?? 0);
  };

  const otrisovki = [];
  const obhod = (ni, roditel, detal) => {
    const u = j.nodes[ni];
    const m = umn(roditel, trs(u));
    const d = detal ?? u.name;
    if (u.mesh !== undefined) {
      for (const pr of j.meshes[u.mesh].primitives) {
        const vao = gl.createVertexArray();
        gl.bindVertexArray(vao);
        atribut(0, pr.attributes.POSITION);
        atribut(1, pr.attributes.NORMAL);
        const ind = j.accessors[pr.indices];
        gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, vidy[ind.bufferView].b);
        gl.bindVertexArray(null);
        const mat = j.materials[pr.material].pbrMetallicRoughness;
        otrisovki.push({
          vao, m, detal: d, chislo: ind.count, tip: ind.componentType, sdvig: ind.byteOffset ?? 0,
          cvet: mat.baseColorFactor.slice(0, 3), mr: [mat.metallicFactor ?? 1, mat.roughnessFactor ?? 1],
        });
      }
    }
    for (const k of u.children ?? []) obhod(k, m, d);
  };
  for (const ni of j.scenes[j.scene ?? 0].nodes) obhod(ni, EDIN, null);
  return otrisovki;
}

// ---------- Показ ----------
export async function zapustit(koren, { model, vybor }) {
  // точки меток вписаны в страницу при сборке — код показа один на все модели
  const METKI = JSON.parse(document.getElementById('m3d-metki').textContent);
  const scena = koren.querySelector('.m3d-scena');
  const sloyMetok = koren.querySelector('.m3d-metki');
  const kartochka = koren.querySelector('.m3d-kartochka');

  const holst = document.createElement('canvas');
  holst.setAttribute('role', 'img');
  holst.setAttribute('aria-label', 'Спортивная парашютная система на манекене, 3D-модель. Стрелками — повернуть, плюс и минус — приблизить.');
  holst.tabIndex = 0;
  const gl = holst.getContext('webgl2', { antialias: true, alpha: true, powerPreference: 'low-power' });
  if (!gl) throw new Error('Браузер не поддерживает WebGL2');
  scena.appendChild(holst);

  const osn = programma(gl, VERSH, OSN);
  const sluzh = programma(gl, VERSH, SLUZH);
  const otrisovki = await zagruzitGlb(gl, model);

  const detali = [...new Set(otrisovki.map((o) => o.detal))];
  const nomerDetali = (kl) => detali.indexOf(kl) + 1;

  const nazvaniya = {};
  for (const li of document.querySelectorAll('.m3d-spisok [data-detal]')) {
    nazvaniya[li.dataset.detal] = {
      imya: li.querySelector('button').textContent.trim(),
      opisanie: li.querySelector('p')?.textContent.trim() ?? '',
    };
  }

  const metki = METKI.map((m) => {
    const el = document.createElement('button');
    el.type = 'button';
    el.className = 'm3d-metka';
    el.textContent = m.n;
    const imya = nazvaniya[m.kl]?.imya ?? '';
    el.setAttribute('aria-label', `${m.n}. ${imya}`);
    el.title = imya;
    el.addEventListener('click', () => vybrat(m.kl));
    sloyMetok.appendChild(el);
    return { ...m, el, vidna: true };
  });

  // ---------- Камера: орбита вокруг цели ----------
  const kam = { cel: [...CEL], ...NACHALO };
  const skor = { az: 0, pol: 0 };
  let polet = null;
  let VP = null, oko = null, shir = 1, vys = 1, dpr = 1;

  function okoKamery() {
    const s = Math.sin(kam.polyar);
    return [kam.cel[0] + kam.radius * s * Math.sin(kam.azimut), kam.cel[1] + kam.radius * Math.cos(kam.polyar),
      kam.cel[2] + kam.radius * s * Math.cos(kam.azimut)];
  }

  // ---------- Отрисовка ----------
  let nuzhenKadr = true, sluzhUstarel = true;
  const kadr = () => { nuzhenKadr = true; sluzhUstarel = true; };
  let vybrannaya = null;

  function narisovat() {
    oko = okoKamery();
    VP = umn(perspektiva(0.56, shir / vys, 0.05, 20), vzglyad(oko, kam.cel));
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    gl.viewport(0, 0, holst.width, holst.height);
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    gl.enable(gl.DEPTH_TEST);
    gl.useProgram(osn.p);
    gl.uniformMatrix4fv(osn.u.uVP, false, VP);
    gl.uniform3fv(osn.u.uOko, oko);
    for (const o of otrisovki) {
      gl.uniformMatrix4fv(osn.u.uM, false, o.m);
      gl.uniform3fv(osn.u.uCvet, o.cvet);
      gl.uniform2fv(osn.u.uMR, o.mr);
      gl.uniform3fv(osn.u.uSvechenie, o.detal === vybrannaya ? PODSVETKA.map((x) => x * 0.35) : [0, 0, 0]);
      gl.bindVertexArray(o.vao);
      gl.drawElements(gl.TRIANGLES, o.chislo, o.tip, o.sdvig);
    }
    gl.bindVertexArray(null);
  }

  // Служебный кадр в четверть размера: номер детали и глубина в каждой точке
  let fbo = null, fboTex = null, fboGl = null, fboW = 0, fboH = 0, sluzhDannye = null;
  function sluzhebnyy() {
    const w = Math.max(1, Math.round(holst.width / 4)), h = Math.max(1, Math.round(holst.height / 4));
    if (w !== fboW || h !== fboH) {
      fboW = w; fboH = h;
      if (fbo) { gl.deleteFramebuffer(fbo); gl.deleteTexture(fboTex); gl.deleteRenderbuffer(fboGl); }
      fbo = gl.createFramebuffer();
      fboTex = gl.createTexture();
      gl.bindTexture(gl.TEXTURE_2D, fboTex);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, w, h, 0, gl.RGBA, gl.UNSIGNED_BYTE, null);
      fboGl = gl.createRenderbuffer();
      gl.bindRenderbuffer(gl.RENDERBUFFER, fboGl);
      gl.renderbufferStorage(gl.RENDERBUFFER, gl.DEPTH_COMPONENT24, w, h);
      gl.bindFramebuffer(gl.FRAMEBUFFER, fbo);
      gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, fboTex, 0);
      gl.framebufferRenderbuffer(gl.FRAMEBUFFER, gl.DEPTH_ATTACHMENT, gl.RENDERBUFFER, fboGl);
      sluzhDannye = new Uint8Array(w * h * 4);
    }
    gl.bindFramebuffer(gl.FRAMEBUFFER, fbo);
    gl.viewport(0, 0, w, h);
    gl.clearColor(0, 1, 1, 1);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    gl.useProgram(sluzh.p);
    gl.uniformMatrix4fv(sluzh.u.uVP, false, VP);
    for (const o of otrisovki) {
      gl.uniformMatrix4fv(sluzh.u.uM, false, o.m);
      gl.uniform1f(sluzh.u.uId, nomerDetali(o.detal));
      gl.bindVertexArray(o.vao);
      gl.drawElements(gl.TRIANGLES, o.chislo, o.tip, o.sdvig);
    }
    gl.bindVertexArray(null);
    gl.readPixels(0, 0, w, h, gl.RGBA, gl.UNSIGNED_BYTE, sluzhDannye);
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    sluzhUstarel = false;
  }

  // точка экрана (в CSS-пикселях) → номер детали и линейная глубина
  const LIN = (z) => (2 * 0.05 * 20) / (20 + 0.05 - (z * 2 - 1) * (20 - 0.05));
  function vTochke(x, y) {
    const px = Math.min(fboW - 1, Math.max(0, Math.floor((x / shir) * fboW)));
    const py = Math.min(fboH - 1, Math.max(0, Math.floor((1 - y / vys) * fboH)));
    const i = (py * fboW + px) * 4, d = sluzhDannye;
    return { id: d[i], glub: LIN((d[i + 1] * 65536 + d[i + 2] * 256 + d[i + 3]) / 16777215) };
  }

  function proekciya(p) {
    const x = VP[0] * p[0] + VP[4] * p[1] + VP[8] * p[2] + VP[12];
    const y = VP[1] * p[0] + VP[5] * p[1] + VP[9] * p[2] + VP[13];
    const w = VP[3] * p[0] + VP[7] * p[1] + VP[11] * p[2] + VP[15];
    return [((x / w + 1) / 2) * shir, ((1 - y / w) / 2) * vys, w];
  }

  function obnovitMetki(tochno) {
    for (const m of metki) {
      const [x, y, w] = proekciya(m.p);
      m.el.style.transform = `translate(${x}px,${y}px) translate(-50%,-50%)`;
      const kKamere = normir(sub(oko, m.p));
      let vidna = dot(m.nr, kKamere) > 0.12;
      if (vidna && tochno) {
        // метка перекрыта, если в её точке экрана что-то ближе к камере, чем она сама
        let svobodno = 0;
        for (const [dx, dy] of [[0, 0], [-4, 0], [4, 0], [0, -4], [0, 4]]) {
          const t = vTochke(x + dx, y + dy);
          if (t.id === 0 || t.glub > w - 0.03) svobodno++;
        }
        vidna = svobodno >= 2;
        m.vidna = vidna;
      } else if (vidna) {
        vidna = m.vidna;
      } else {
        m.vidna = false;
      }
      m.el.classList.toggle('skryta', !vidna);
      m.el.tabIndex = vidna ? 0 : -1;
    }
  }

  let pokoy = 0;
  function cikl(t) {
    requestAnimationFrame(cikl);
    if (polet) shagPoleta(t);
    if (Math.abs(skor.az) > 1e-4 || Math.abs(skor.pol) > 1e-4) {
      povernut(skor.az, skor.pol);
      skor.az *= 0.88;
      skor.pol *= 0.88;
    }
    if (nuzhenKadr) {
      nuzhenKadr = false;
      narisovat();
      obnovitMetki(false);
      pokoy = t;
      return;
    }
    // картинка стоит 150 мс — уточнить перекрытие меток служебным кадром
    if (sluzhUstarel && t - pokoy > 150) {
      sluzhebnyy();
      obnovitMetki(true);
    }
  }

  function razmer() {
    shir = scena.clientWidth; vys = scena.clientHeight;
    if (!shir || !vys) return;
    dpr = Math.min(devicePixelRatio, 2);
    holst.width = Math.round(shir * dpr);
    holst.height = Math.round(vys * dpr);
    kadr();
  }
  new ResizeObserver(razmer).observe(scena);
  razmer();

  // ---------- Управление: мышь, палец, колесо, клавиши ----------
  function povernut(daz, dpol) {
    kam.azimut += daz;
    kam.polyar = Math.min(2.7, Math.max(0.25, kam.polyar + dpol));
    kadr();
  }
  function priblizit(k) {
    kam.radius = Math.min(3.4, Math.max(0.45, kam.radius * k));
    kadr();
  }

  const palcy = new Map();
  let nazhatie = null, shchipok = 0;
  holst.addEventListener('pointerdown', (e) => {
    koren.classList.add('m3d-trogali');
    holst.setPointerCapture(e.pointerId);
    palcy.set(e.pointerId, [e.clientX, e.clientY]);
    nazhatie = palcy.size === 1 ? [e.clientX, e.clientY] : null;
    polet = null;
    skor.az = skor.pol = 0;
    if (palcy.size === 2) {
      const [a, b] = [...palcy.values()];
      shchipok = Math.hypot(a[0] - b[0], a[1] - b[1]);
    }
  });
  holst.addEventListener('pointermove', (e) => {
    const bylo = palcy.get(e.pointerId);
    if (!bylo) return;
    palcy.set(e.pointerId, [e.clientX, e.clientY]);
    if (palcy.size === 1) {
      skor.az = -(e.clientX - bylo[0]) * 0.008;
      skor.pol = -(e.clientY - bylo[1]) * 0.008;
      povernut(skor.az, skor.pol);
    } else if (palcy.size === 2) {
      const [a, b] = [...palcy.values()];
      const d = Math.hypot(a[0] - b[0], a[1] - b[1]);
      if (shchipok) priblizit(shchipok / d);
      shchipok = d;
    }
  });
  const otpustit = (e) => {
    palcy.delete(e.pointerId);
    if (palcy.size < 2) shchipok = 0;
    if (e.type === 'pointerup' && nazhatie && Math.hypot(e.clientX - nazhatie[0], e.clientY - nazhatie[1]) < 6) {
      skor.az = skor.pol = 0;
      const r = holst.getBoundingClientRect();
      if (sluzhUstarel) sluzhebnyy();
      const kl = detali[vTochke(e.clientX - r.left, e.clientY - r.top).id - 1];
      if (kl && nazvaniya[kl]) vybrat(kl);
    }
    nazhatie = null;
  };
  holst.addEventListener('pointerup', otpustit);
  holst.addEventListener('pointercancel', otpustit);
  holst.addEventListener('wheel', (e) => {
    e.preventDefault();
    polet = null;
    priblizit(Math.exp(e.deltaY * 0.001));
  }, { passive: false });
  holst.addEventListener('keydown', (e) => {
    const d = { ArrowLeft: [0.15, 0], ArrowRight: [-0.15, 0], ArrowUp: [0, 0.12], ArrowDown: [0, -0.12] }[e.key];
    if (d) { e.preventDefault(); povernut(...d); }
    else if (e.key === '+' || e.key === '=') priblizit(0.9);
    else if (e.key === '-') priblizit(1.1);
  });

  // ---------- Выбор детали и облёт к ней ----------
  function vybrat(kl) {
    koren.classList.add('m3d-trogali');
    vybrannaya = kl;
    for (const m of metki) m.el.classList.toggle('aktivna', m.kl === kl);
    const info = nazvaniya[kl];
    const m = metki.find((x) => x.kl === kl);
    if (info && m) {
      kartochka.hidden = false;
      kartochka.querySelector('.m3d-k-nomer').textContent = m.n;
      kartochka.querySelector('.m3d-k-imya').textContent = info.imya;
      kartochka.querySelector('.m3d-k-opisanie').textContent = info.opisanie;
      // смотрим вдоль нормали детали, но не снизу; цель — между деталью и центром
      const n = normir([m.nr[0], Math.max(m.nr[1], 0.12), m.nr[2]]);
      const cel = m.p.map((x, i) => x + (CEL[i] - x) * 0.35);
      // карточка закрывает низ окна — деталь ставится в середину оставшейся части
      const radius = 1.25;
      const dolya = kartochka.offsetHeight / vys;
      cel[1] -= (dolya / 2) * 2 * radius * Math.tan(0.28);
      letet({ cel, azimut: Math.atan2(n[0], n[2]), polyar: Math.acos(n[1]), radius });
    }
    vybor?.(kl);
    kadr();
  }

  function letet(kuda) {
    // по азимуту — кратчайшим путём
    let daz = (kuda.azimut - kam.azimut) % (2 * Math.PI);
    if (daz > Math.PI) daz -= 2 * Math.PI;
    if (daz < -Math.PI) daz += 2 * Math.PI;
    const k = { ...kuda, azimut: kam.azimut + daz };
    if (bezDvizheniya) { Object.assign(kam, k, { cel: [...k.cel] }); kadr(); return; }
    polet = { t0: null, ot: { ...kam, cel: [...kam.cel] }, k };
  }

  function shagPoleta(t) {
    if (polet.t0 === null) polet.t0 = t;
    const x = Math.min((t - polet.t0) / 700, 1);
    const e = x < 0.5 ? 4 * x * x * x : 1 - (-2 * x + 2) ** 3 / 2;
    const { ot, k } = polet;
    for (const p of ['azimut', 'polyar', 'radius']) kam[p] = ot[p] + (k[p] - ot[p]) * e;
    kam.cel = ot.cel.map((v, i) => v + (k.cel[i] - v) * e);
    if (x === 1) polet = null;
    kadr();
  }

  koren.querySelector('.m3d-k-zakryt').addEventListener('click', () => {
    kartochka.hidden = true;
    vybrannaya = null;
    for (const m of metki) m.el.classList.remove('aktivna');
    vybor?.(null);
    letet({ cel: [...CEL], ...NACHALO });
  });

  requestAnimationFrame(cikl);
  koren.dataset.gotovo = '1';
  return { vybrat, get vybrannaya() { return vybrannaya; } };
}
