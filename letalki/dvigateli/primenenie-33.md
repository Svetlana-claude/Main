# «33» — применение по модификациям

<section class="dv slide oblozhka odin sinii">
<p class="metka">Проект «33» · применение по модификациям · ноябрь 2026</p>
<h1>«33» — какая версия<br><span class="p33">для какой работы</span></h1>
<p class="podzag">Один планер, три силовые установки: электрическая, ДВС + СЭВ инжектор на бензине и на керосине. У каждой — своя работа</p>
<div class="fakty">
<div><b><span class="tsv el"></span>электро</b><span>до 800 км · 9 ч</span></div>
<div><b><span class="tsv bz"></span>бензин + СЭВ</b><span>≈ 3 850 км · 40 ч</span></div>
<div><b><span class="tsv ks"></span>керосин + СЭВ</b><span>≈ 3 200 км · 34 ч</span></div>
</div>
<img class="render" src="../img/proekt-33.png" alt="Рендер БПЛА «33»">
</section>

<section class="dv slide">
<p class="metka">1 · Задача × модификация</p>
<h2>Восемь направлений — кому что</h2>
<table class="sravnenie matr">
<thead><tr><th class="param">Направление</th><th class="el">Электро</th><th class="bz">Бензин + СЭВ</th><th class="ks">Керосин + СЭВ</th></tr></thead>
<tbody>
<tr><td>Трубопроводы, линейные объекты</td><td><span class="oc v1">подходит</span><span class="pr">участки до ≈ 340 км от точки взлёта</span></td><td><span class="oc v2">лучший выбор</span><span class="pr">участки до ≈ 1 600 км за вылет</span></td><td><span class="oc v1">подходит</span><span class="pr">там, где есть только керосин</span></td></tr>
<tr><td>ЛЭП и энергосети</td><td><span class="oc v2">лучший выбор</span><span class="pr">типовой обход — сотни км, час дешевле всех</span></td><td><span class="oc v1">подходит</span><span class="pr">для дальних магистралей</span></td><td><span class="oc v0">избыточно</span></td></tr>
<tr><td>Леса и пожары</td><td><span class="oc v1">подходит</span><span class="pr">дневной патруль</span></td><td><span class="oc v2">лучший выбор</span><span class="pr">сутки над районом, тепловизор, связь для групп</span></td><td><span class="oc v1">подходит</span></td></tr>
<tr><td>Картография и кадастр</td><td><span class="oc v2">лучший выбор</span><span class="pr">нет вибраций — чёткий снимок</span></td><td><span class="oc v1">подходит</span><span class="pr">большие площади, нужна виброразвязка</span></td><td><span class="oc v0">избыточно</span></td></tr>
<tr><td>Ретранслятор связи</td><td><span class="oc v0">до 9 ч</span><span class="pr">короткие работы</span></td><td><span class="oc v2">лучший выбор</span><span class="pr">сутки с 4–5 кг нагрузки</span></td><td><span class="oc v2">лучший выбор</span><span class="pr">с кораблей и баз флота</span></td></tr>
<tr><td>Арктика, ледовая разведка</td><td><span class="oc vx">не подходит</span><span class="pr">мороз отнимает дальность</span></td><td><span class="oc v1">подходит</span><span class="pr">СЭВ запускает на морозе</span></td><td><span class="oc v2">лучший выбор</span><span class="pr">ТС-1 на всех северных базах</span></td></tr>
<tr><td>Экология и радиация</td><td><span class="oc v2">лучший выбор</span><span class="pr">нет своего выхлопа для газоанализа</span></td><td><span class="oc v0">радиометр — да, газ — нет</span></td><td><span class="oc v0">радиометр — да, газ — нет</span></td></tr>
<tr><td>Охрана границ и периметров</td><td><span class="oc v1">подходит</span><span class="pr">тихое наблюдение объектов</span></td><td><span class="oc v2">лучший выбор</span><span class="pr">сутки патруля, SAR на генераторе</span></td><td><span class="oc v2">лучший выбор</span><span class="pr">морские границы, единое топливо</span></td></tr>
</tbody>
</table>
<p class="pomet">Оценка по характеристикам документа «"33" — выбор двигателя». Участок трассы — половина дальности с запасом 15 %: туда и обратно с одной точки взлёта.</p>
</section>

<section class="dv slide">
<p class="metka">2 · Электро</p>
<h2>Электро — регулярная работа рядом с людьми</h2>
<div class="profil">
<div class="kol el" style="display:flex;flex-direction:column">
<h3>Особенности</h3>
<dl><dt>Дальность</dt><dd>≥ 800 км (цель 1 200)</dd><dt>В воздухе</dt><dd>≥ 9 ч (цель 12–14)</dd><dt>Час полёта</dt><dd>100–150 ₽</dd><dt>Нагрузка</dt><dd>до 1,5 кг</dd></dl>
<p class="sila">тихий: объект не слышит аппарат</p>
<p class="sila">нет выхлопа — чистый газоанализ</p>
<p class="sila">нет вибраций — резкий снимок</p>
<p class="sila">без топлива: можно у жилья, на предприятиях</p>
<p class="slabo">на морозе −25 % дальности без подогрева</p>
<p class="slabo">тяжёлая нагрузка съедает дальность</p>
<p class="zakazchiki">Заказчики: кадастровые инженеры и регионы, электросети, природнадзор и промышленность, атомная отрасль, лесхозы.</p>
</div>
<table class="sravnenie polety">
<thead><tr><th class="el">Типовой полёт</th><th class="el">В цифрах</th><th class="el">Нагрузка</th></tr></thead>
<tbody>
<tr><td>Обход ЛЭП</td><td>≈ 340 км линии от точки взлёта и обратно, ≈ 8 ч</td><td>ортофото, обзорная камера</td></tr>
<tr><td>Аэрофотосъёмка под кадастр</td><td>≈ 150–250 км² за вылет (оценка)</td><td>камера для ортофотосъёмки</td></tr>
<tr><td>Выбросы промзоны, полигона</td><td>облёт контура и шлейфа, 3–6 ч без своего выхлопа в замере</td><td>газоанализатор</td></tr>
<tr><td>Радиационный контроль</td><td>сетка облёта вокруг АЭС или хвостохранилища, 6–9 ч</td><td>радиометр</td></tr>
<tr><td>Дневной патруль леса</td><td>световой день над районом</td><td>обзорная камера</td></tr>
<tr><td>Скрытное наблюдение</td><td>часы над объектом, не слышно с земли</td><td>выдвижная обзорная камера</td></tr>
</tbody>
</table>
</div>
<p class="pomet">Цифры — по справке и расчёту «выбор двигателя»; площадь съёмки — оценка по полосе захвата камеры с перекрытием.</p>
</section>

<section class="dv slide">
<p class="metka">3 · Бензин + СЭВ инжектор</p>
<h2>Бензин + СЭВ — дальние и долгие задачи</h2>
<div class="profil">
<div class="kol bz" style="display:flex;flex-direction:column">
<h3>Особенности</h3>
<dl><dt>Дальность</dt><dd>≈ 3 850 км (бак 7 л)</dd><dt>В воздухе</dt><dd>≈ 40 ч</dd><dt>Час полёта</dt><dd>400–650 ₽</dd><dt>Сутки в воздухе</dt><dd>с 4–5 кг нагрузки</dd></dl>
<p class="sila">в 4–9 раз дальше электро</p>
<p class="sila">генератор питает радиолокатор и лидар</p>
<p class="sila">запуск за 45 с, в мороз без ручных манипуляций</p>
<p class="sila">свой впрыск, поставка за неделю, сервис в России</p>
<p class="slabo">шум и вибрации — нужна виброразвязка камер</p>
<p class="slabo">собственный выхлоп мешает газоанализу</p>
<p class="zakazchiki">Заказчики: нефтегаз и трубопроводы, МЧС и лесная охрана, операторы связи, геологоразведка, охрана границ.</p>
</div>
<table class="sravnenie polety">
<thead><tr><th class="bz">Типовой полёт</th><th class="bz">В цифрах</th><th class="bz">Нагрузка</th></tr></thead>
<tbody>
<tr><td>Патруль трубопровода</td><td>≈ 1 600 км трассы от точки взлёта и обратно за вылет</td><td>ортофото, обзорная камера</td></tr>
<tr><td>Ретранслятор над районом ЧС</td><td>сутки над точкой, радиус связи ≈ 225 км с 3 000 м</td><td>ретранслятор</td></tr>
<tr><td>Лесной пожар</td><td>сутки над районом: очаги, кромка, связь для групп</td><td>тепловизор, ретранслятор</td></tr>
<tr><td>Охрана границы</td><td>≈ 1 500 км рубежа за вылет, днём и ночью</td><td>SAR, обзорная камера</td></tr>
<tr><td>Лидарная съёмка трассы</td><td>рельеф и просеки на сотни км</td><td>лидар 1,5–3 кг</td></tr>
<tr><td>Доставка в удалённые точки</td><td>сброс 3–5 кг: аптечки, буи, датчики</td><td>грузовой отсек</td></tr>
</tbody>
</table>
</div>
<p class="pomet">Дальность и время — с СЭВ инжектором; с карбюратором было бы ≈ 3 100 км и ≈ 32 ч. Радиус связи — расчёт радиогоризонта.</p>
</section>

<section class="dv slide">
<p class="metka">4 · Керосин + СЭВ инжектор</p>
<h2>Керосин + СЭВ — флот, Север, госзаказчик</h2>
<div class="profil">
<div class="kol ks" style="display:flex;flex-direction:column">
<h3>Особенности</h3>
<dl><dt>Дальность</dt><dd>≈ 3 200 км (бак 7 л)</dd><dt>В воздухе</dt><dd>≈ 34 ч</dd><dt>Час полёта</dt><dd>700–1 100 ₽</dd><dt>Сутки в воздухе</dt><dd>с 3–4 кг нагрузки</dd></dl>
<p class="sila">керосин не вспыхивает при обычной температуре — можно хранить на корабле</p>
<p class="sila">одно топливо с авиацией и флотом</p>
<p class="sila">ТС-1 не мутнеет до −60 °C</p>
<p class="sila">СЭВ на керосине уже запускался — импортный двигатель на тяжёлом топливе не нужен</p>
<p class="slabo">расход выше бензинового, час дороже</p>
<p class="slabo">в сильный мороз — подогрев перед запуском</p>
<p class="zakazchiki">Заказчики: флот и морские службы, Севморпуть и порты, северные аэродромы и базы, силовые ведомства.</p>
</div>
<table class="sravnenie polety">
<thead><tr><th class="ks">Типовой полёт</th><th class="ks">В цифрах</th><th class="ks">Нагрузка</th></tr></thead>
<tbody>
<tr><td>Ледовая разведка по трассе Севморпути</td><td>≈ 1 350 км вперёд по курсу и обратно; сквозь облака и полярную ночь</td><td>SAR, обзорная камера</td></tr>
<tr><td>Работа с корабля</td><td>взлёт с катапульты, посадка на парашюте с баллонетом</td><td>любая из справки</td></tr>
<tr><td>Морская граница</td><td>сутки патруля над акваторией</td><td>SAR, обзорная камера</td></tr>
<tr><td>Связь для судов и экспедиций</td><td>сутки ретранслятором над районом</td><td>ретранслятор</td></tr>
<tr><td>Северная база</td><td>заправка тем же ТС-1, что у вертолётов и самолётов</td><td>—</td></tr>
</tbody>
</table>
</div>
<p class="pomet">Посадка на корабль и подбор с воды — проверить отдельно: баллонет в нижней части фюзеляжа рассчитан на землю.</p>
</section>

<section class="dv slide">
<p class="metka">5 · Один маршрут — разная цена</p>
<h2>Короткая работа — электро, длинная — СЭВ</h2>
<div class="dva-grafika">
<div class="grafik">
<h4>Цена одного вылета <small>— ₽, топливо и износ, крейсер 95 км/ч</small></h4>
<p class="legenda-g"><span class="p"><span class="tsv el"></span>электро</span><span class="p"><span class="tsv bz"></span>бензин + СЭВ</span><span class="p"><span class="tsv ks"></span>керосин + СЭВ</span></p>
<div class="gs"><span class="im"><b>300 км</b></span><div class="dor"><div class="pl el" style="width:1.8%"></div><span class="zn" style="left:1.8%">≈ 400</span></div></div>
<div class="gs"><span class="im"></span><div class="dor"><div class="pl bz" style="width:7.6%"></div><span class="zn" style="left:7.6%">≈ 1 700</span></div></div>
<div class="gs" style="margin-bottom:4mm"><span class="im"></span><div class="dor"><div class="pl ks" style="width:13.1%"></div><span class="zn" style="left:13.1%">≈ 2 900</span></div></div>
<div class="gs"><span class="im"><b>800 км</b></span><div class="dor"><div class="pl el" style="width:4.8%"></div><span class="zn" style="left:4.8%">≈ 1 050</span></div></div>
<div class="gs"><span class="im"></span><div class="dor"><div class="pl bz" style="width:20%"></div><span class="zn" style="left:20%">≈ 4 400</span></div></div>
<div class="gs" style="margin-bottom:4mm"><span class="im"></span><div class="dor"><div class="pl ks" style="width:34.5%"></div><span class="zn" style="left:34.5%">≈ 7 600</span></div></div>
<div class="gs"><span class="im"><b>2 000 км</b></span><div class="dor"><span class="zn" style="left:0;padding-left:0;color:var(--seryy)">электро не долетает</span></div></div>
<div class="gs"><span class="im"></span><div class="dor"><div class="pl bz" style="width:50%"></div><span class="zn" style="left:50%">≈ 11 000</span></div></div>
<div class="gs" style="margin-bottom:4mm"><span class="im"></span><div class="dor"><div class="pl ks" style="width:85.9%"></div><span class="zn" style="left:85.9%">≈ 18 900</span></div></div>
<div class="gs"><span class="im"><b>Сутки</b></span><div class="dor"><span class="zn" style="left:0;padding-left:0;color:var(--seryy)">электро столько не держится</span></div></div>
<div class="gs"><span class="im"></span><div class="dor"><div class="pl bz" style="width:57.3%"></div><span class="zn" style="left:57.3%">≈ 12 600</span></div></div>
<div class="gs"><span class="im"></span><div class="dor"><div class="pl ks" style="width:98.2%"></div><span class="zn" style="left:72%;color:#fff">≈ 21 600</span></div></div>
<p class="pomet">Шкала до 22 000 ₽. Час: электро ≈ 125 ₽, бензин + СЭВ ≈ 525 ₽, керосин + СЭВ ≈ 900 ₽ — середины оценок.</p>
</div>
<div class="kol p33" style="align-self:start">
<h3>Что из этого следует</h3>
<ul class="zadachi">
<li>До 800 км электро дешевле в 4–7 раз — регулярные облёты выгодно отдавать ему.</li>
<li>Дальше 800 км и дольше 9 ч работает только СЭВ — там цена вылета сравнивается уже с вертолётом и самолётом, а не с электро.</li>
<li>Керосин дороже бензина в 1,7 раза; его берут, когда бензина нет или его нельзя держать.</li>
<li>Один планер и одни нагрузки на всех — у заказчика может быть парк из разных версий под разные работы.</li>
</ul>
</div>
</div>
</section>

<section class="dv slide">
<p class="metka">6 · Линейка «33»</p>
<h2>Три версии — одна платформа</h2>
<div class="itog" style="grid-template-columns:repeat(3,1fr)">
<div class="var4 el"><span class="stup">Сейчас · испытания</span><p class="resh">«33» Электро</p><p>Первая версия: подтвердить на лётных испытаниях 800 км и 9 ч. Рынок — регулярные работы: съёмка, сети, экология, радиация.</p></div>
<div class="var4 bz"><span class="stup">2027 · вторая версия</span><p class="resh">«33» + СЭВ, бензин</p><p>«Дальняя» версия для коммерческого рынка: трубопроводы, лесные пожары, связь, граница. Свой впрыск на своём аппарате — витрина для обоих проектов.</p></div>
<div class="var4 ks"><span class="stup">Под заказ</span><p class="resh">«33» + СЭВ, керосин</p><p>Версия для флота, Севера и госзаказчика с единым топливом. Делается из бензиновой: тот же планер, СЭВ настраивается на керосин.</p></div>
</div>
<div class="proverit"><b>Общее у всех трёх</b>
<ol>
<li>Планер, крыло и оперение «33».</li>
<li>Целевые нагрузки из справки: ортофото, обзорная камера, SAR, ретранслятор, газоанализатор, радиометр.</li>
<li>Взлёт с катапульты, посадка на парашюте с баллонетом — без аэродрома.</li>
<li>Сменной остаётся силовая установка и запас энергии; насколько быстро она меняется — проверить на прототипе.</li>
</ol></div>
</section>
