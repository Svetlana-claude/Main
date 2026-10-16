// Сетки месяцев для блоков календаря.
// Выходные и переносы — по постановлению Правительства РФ от 17.09.2026 № 1187
// (2027 год) и по календарю 2026 года (31 декабря 2026 — выходной).

const MESYACY = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль",
  "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"];
// Римские номера (вариант E) и «символы элементов» (вариант F)
const RIM = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII"];
const SIM = ["Ян", "Фв", "Мр", "Ап", "Ма", "Ин", "Ил", "Ав", "Сн", "Ок", "Нб", "Дк"];
const DNI = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];

// Нерабочие праздничные дни и выходные, перенесённые на будни
const VYHODNYE = new Set([
  "2026-12-31",
  "2027-01-01", "2027-01-02", "2027-01-03", "2027-01-04", "2027-01-05",
  "2027-01-06", "2027-01-07", "2027-01-08", "2027-01-09", "2027-01-10",
  "2027-02-21", "2027-02-22", "2027-02-23",
  "2027-03-08", "2027-05-01", "2027-05-02", "2027-05-03", "2027-05-08",
  "2027-05-09", "2027-05-10", "2027-06-12", "2027-06-13", "2027-06-14",
  "2027-11-04", "2027-11-05", "2027-12-31",
]);
// Праздники как даты — помечаются точкой
const PRAZDNIKI = new Set([
  "2027-01-01", "2027-01-02", "2027-01-03", "2027-01-04", "2027-01-05",
  "2027-01-06", "2027-01-07", "2027-01-08", "2027-02-23", "2027-03-08",
  "2027-05-01", "2027-05-09", "2027-06-12", "2027-11-04",
]);
// Рабочие субботы
const RABOCHIE = new Set(["2027-02-20"]);

const PRIMECHANIYA = {
  "2026-12": "31 декабря — выходной",
  "2027-1": "1–10 января — новогодние каникулы",
  "2027-2": "20 февраля — рабочая суббота; 21–23 — выходные",
};

function kluch(y, m, d) {
  return `${y}-${String(m).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
}

function RisovatMesyac(el) {
  const y = +el.dataset.y, m = +el.dataset.m;
  const dney = new Date(y, m, 0).getDate();
  const sdvig = (new Date(y, m - 1, 1).getDay() + 6) % 7; // понедельник — первый
  const yacheyki = [];
  DNI.forEach((d, i) => yacheyki.push(`<span class="dn${i > 4 ? " vyh" : ""}">${d}</span>`));
  for (let i = 0; i < sdvig; i++) yacheyki.push('<span class="pust"></span>');
  for (let d = 1; d <= dney; d++) {
    const k = kluch(y, m, d);
    const nedelya = (sdvig + d - 1) % 7;
    const klassy = ["d"];
    if (RABOCHIE.has(k)) klassy.push("rab");
    else if (nedelya > 4 || VYHODNYE.has(k)) klassy.push("vyh");
    if (PRAZDNIKI.has(k)) klassy.push("prazd");
    yacheyki.push(`<span class="${klassy.join(" ")}">${d}</span>`);
  }
  // Сетка заказчика всегда в шесть строк: пустые клетки добиваются до 42
  if ("kletki" in el.dataset) while (yacheyki.length < 49) yacheyki.push('<span class="pust"></span>');
  const ikon = el.dataset.ikon
    ? `<svg class="mes-ikon" viewBox="0 0 240 90"><use href="#${el.dataset.ikon}"/></svg>` : "";
  const prim = PRIMECHANIYA[`${y}-${m}`] || "";
  el.innerHTML = `
    <div class="mes-zag">
      <span class="mes-sim">${SIM[m - 1]}</span><span class="mes-rim">${RIM[m - 1]}</span>
      <span class="mes-nom">${String(m).padStart(2, "0")}</span>
      <span class="mes-imya">${MESYACY[m - 1]}</span>
      <span class="mes-god">${y}</span>${ikon}
    </div>
    <div class="shapka-mes"><span>${MESYACY[m - 1]}</span><span>${y}</span></div>
    <div class="dni">${yacheyki.join("")}</div>
    <p class="prim">${prim}</p>`;
}

document.querySelectorAll(".mes").forEach(RisovatMesyac);
document.body.classList.add("gotovo");

// Режим печати одного варианта: index.html?v=a
const vybor = new URLSearchParams(location.search).get("v");
if (vybor) {
  document.body.classList.add("pechat");
  document.querySelectorAll(".var").forEach(s => { if (s.id !== "var-" + vybor) s.remove(); });
  document.querySelector(".titul").remove();
}
