// Лёгкая часть страницы: обложка, список деталей и кнопка «Покрутить в 3D».
// Тяжёлое (three.js и модель) подгружается только по нажатию — до этого
// страница весит столько же, сколько картинка-обложка.

const koren = document.querySelector('[data-m3d]');
const knopka = koren.querySelector('.m3d-zapusk');
const spisok = document.querySelector('.m3d-spisok');
let prosmotr = null;
let zagruzka = null;

function zapustit() {
  if (!zagruzka) {
    koren.classList.add('m3d-gruzitsya');
    knopka.disabled = true;
    zagruzka = import('./prosmotr.js')
      .then((m) => m.zapustit(koren, { model: koren.dataset.m3d, vybor: otmetitVSpiske }))
      .then((p) => {
        prosmotr = p;
        koren.classList.remove('m3d-gruzitsya');
        koren.classList.add('m3d-gotovo');
        return p;
      })
      .catch((e) => {
        console.error(e);
        koren.classList.remove('m3d-gruzitsya');
        koren.classList.add('m3d-oshibka');
        knopka.disabled = false;
        zagruzka = null;
      });
  }
  return zagruzka;
}

function otmetitVSpiske(kl) {
  for (const li of spisok.querySelectorAll('[data-detal]')) {
    const da = li.dataset.detal === kl;
    li.classList.toggle('vybrana', da);
    li.querySelector('button').setAttribute('aria-pressed', da ? 'true' : 'false');
  }
}

knopka.addEventListener('click', zapustit);

// Нажатие на деталь в списке: запускает 3D, если ещё не запущено, и показывает деталь
spisok.addEventListener('click', (e) => {
  const li = e.target.closest('[data-detal]');
  if (!li) return;
  const kl = li.dataset.detal;
  otmetitVSpiske(kl);
  if (prosmotr) prosmotr.vybrat(kl);
  else zapustit()?.then((p) => p && p.vybrat(kl));
});
