// Построение дизайнерских сеток вариантов G и H.
// Метки модулей G рисуются всегда, слой .konstr виден только в режиме ?setka.

const SVGNS = "http://www.w3.org/2000/svg";

function Element(rod, imya, atr) {
  const el = document.createElementNS(SVGNS, imya);
  Object.entries(atr).forEach(([k, v]) => el.setAttribute(k, v));
  rod.appendChild(el);
  return el;
}

// G: 12 колонок × 8 рядов, поля 12 мм, средник 3 мм (лист 297 × 210)
const G = { pole: 12, sred: 3, kol: 12, ryad: 8, shir: 20, vys: 20.625 };
function GKol(i) { return G.pole + i * (G.shir + G.sred); }
function GRyad(j) { return G.pole + j * (G.vys + G.sred); }

document.querySelectorAll(".g-kresty").forEach(kresty => {
  for (let i = 0; i <= G.kol; i++) for (let j = 0; j <= G.ryad; j++) {
    const x = i < G.kol ? GKol(i) : GKol(i - 1) + G.shir;
    const y = j < G.ryad ? GRyad(j) : GRyad(j - 1) + G.vys;
    Element(kresty, "path", { d: `M${x - 1.2},${y} h2.4 M${x},${y - 1.2} v2.4` });
  }
});
document.querySelectorAll(".g-konstr").forEach(gKonstr => {
  for (let i = 0; i < G.kol; i++) for (let j = 0; j < G.ryad; j++)
    Element(gKonstr, "rect", { x: GKol(i), y: GRyad(j), width: G.shir, height: G.vys });
});

// H: шесть колонок, поля 14 мм, средник 5 мм; горизонтальные полосы Unigrid
document.querySelectorAll(".h-konstr").forEach(hKonstr => {
  const shir = (297 - 28 - 5 * 5) / 6;
  for (let i = 0; i < 6; i++)
    Element(hKonstr, "rect", { x: 14 + i * (shir + 5), y: 14, width: shir, height: 182 });
  (hKonstr.dataset.polosy || "22 86 130").split(" ").forEach(y => Element(hKonstr, "path", { d: `M0,${y} H297`, class: "polosa-u" }));
});

if (new URLSearchParams(location.search).has("setka")) document.body.classList.add("setka");
