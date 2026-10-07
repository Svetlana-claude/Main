# Фото блока «Дропзоны мира» — откуда и на каких условиях

Блок на главной сайта (`resources/views/partials/home/dropzony.blade.php`),
фото — `public/images/dropzony/<slug>.webp`, кадр 4:3, до 960 px.

Прежние фото пришли с сайта на Tilda, а туда — со стороннего сайта; прав на них
не было. 08.10.2026 их заменили на виды мест в общественном достоянии, а затем —
на снимки **с парашютистами** под свободными лицензиями:

- **CC0 / PDM / общественное достояние** — подпись автора не нужна.
- **CC BY** — можно использовать, изменять и публиковать, в том числе в
  коммерческих целях, **при указании автора и лицензии** со ссылками.
- **CC BY-SA** — то же, что CC BY; изменённый снимок распространяется на тех же
  условиях. Обрезка и уменьшение под кадр 4:3 — изменение, поэтому сами
  обработанные файлы тоже под CC BY-SA.

Подпись «Фото: автор, лицензия» выводится на сайте поверх снимка — и в
карточке, и в окне с полным текстом. Данные подписи — массив `$foto` в шаблоне.

| Место | Что на снимке | Лицензия | Автор | Страница снимка |
|---|---|---|---|---|
| Пальма Джумейра (`dubai`) | тандем над Пальмой | CC0 | palak2511 | https://wordpress.org/photos/photo/312695e31f/ |
| Эверест (`everest`) | свободное падение на фоне Эвереста | PDM | Explore Himalaya | https://www.flickr.com/photos/28595037@N08/31097025171 |
| Майсур (`maysur`) | купола «Акаш Ганги», группы ВВС Индии | CC BY 4.0 | Sanil Nath | https://commons.wikimedia.org/w/index.php?curid=145345121 |
| Пустыня Намиб (`namib`) | тандем над пустыней | CC BY 2.0 | hillsieboy | https://www.flickr.com/photos/81681077@N00/185617370 |
| Восс (`voss`) | **Аурланнсфьорд** со Стегастейна, не сам Восс | CC BY 2.0 | PhotoHenning | https://www.flickr.com/photos/31467556@N00/15875275173 |
| Рио-де-Жанейро (`rio`) | прыжок над Барра-да-Тижука | CC BY 3.0 | Tiago Cobra | https://commons.wikimedia.org/w/index.php?curid=56248529 |
| Долина Лаутербруннен (`lauterbrunnen`) | тандем **над Сьоном**, Швейцарские Альпы | CC BY-SA 4.0 | Romandie Parachutisme | https://commons.wikimedia.org/wiki/File:Saut_en_parachute_tandem_%C3%A0_Sion.jpg |
| Квинсленд (`kvinslend`) | тандем Skydive Cairns | CC BY 2.0 | Benson FY | https://www.flickr.com/photos/49973921@N06/5360265968 |
| Гранд-Каньон (`grand-kanon`) | парашютист с флагом **над горами Аризоны** у Тусона | общественное достояние (снимок ВВС США) | Senior Airman Chris Massey | https://commons.wikimedia.org/wiki/File:Thunder_and_Lightning_over_Arizona_Open_House_160312-F-ZT877-0101.jpg |
| Ледник Фокс (`foks`) | купол над горами Западного побережья | CC BY-SA 4.0 | Stewart Nimmo | https://commons.wikimedia.org/wiki/File:TWC_Skydiving%E2%80%A2_Stewart_Nimmo_%E2%80%A2_MRD_8637.jpg |
| Большое Грызлово (`gryzlovo`) | наш аэродром | своё | — | с прежнего сайта Главпрыга |

Тексты лицензий: [CC BY 2.0](https://creativecommons.org/licenses/by/2.0/),
[CC BY 3.0](https://creativecommons.org/licenses/by/3.0/),
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/),
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).

**Не точное место.** Три снимка сделаны рядом, а не в самой дропзоне: Восс
(Аурланнсфьорд, тот же регион Западной Норвегии), Лаутербруннен (Сьон, те же
Швейцарские Альпы), Гранд-Каньон (Аризона у Тусона). Свободных снимков с
парашютистами в этих местах не нашлось; alt на сайте называет то, что на
кадре на самом деле. Если заказчик пришлёт свои кадры или купит стоковые —
файлы меняются по тем же именам.

Поиск — Openverse (`api.openverse.org`) и Wikimedia Commons.
