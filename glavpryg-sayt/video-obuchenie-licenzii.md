# Ролики страницы «Обучение» — откуда и на каких условиях

Страница `resources/views/services/obuchenie.blade.php`, ролики —
`public/video/<имя>.mp4` и обложка `<имя>.jpg`, кадр 4:3, 960×720, без звука.
Подпись автора и лицензии выводится под роликом (шаблон `partials/rolik.blade.php`).

## Блок «Как пройти обучение»

Своя съёмка Главпрыга, подпись не нужна.

| Файл | Что на ролике | Откуда |
|---|---|---|
| `aff-otdelenie` | у двери, отделение с инструкторами, самолёт уходит | видео заказчика `gx010054-1.mp4` (камера инструктора), 7–17 с |
| `aff-padenie` | свободное падение, инструктор держит за систему | то же видео, 24–33 с |
| `aff-kupol` | раскрытие и купол, вид от первого лица | ролик самостоятельного прыжка, 15,5–23 с |
| `aff-posadka` | заход, подушка, приземление на ноги, вид с земли | видео заказчика `00995.mp4`, целиком (9,6 с) |

Прежние варианты посадки — посадка на пляж (Philip Thomas, CC BY 3.0) и своя
анимация «камера 360» (исходник `glavpryg-sayt/animaciya-posadka.html`) —
заменены съёмкой заказчика. Прежние отделение и падение были нарезаны из
ролика тандема.

## Блок «Нормальное раскрытие парашюта»

| Файл | Что на ролике | Откуда |
|---|---|---|
| `norma-raskrytie` | рывок, вытяжной, купол выходит и наполняется, клеванты в руках; квадрат 720×720, окно кадра плавно идёт за действием | видео заказчика `video-2026-10-12-00-17-46.mp4` (камера 360, вертикаль), 19,5–31,5 с |

Прежний ролик блока — `otk-raskrytie` (SkydivePhoto, CC0); файл остался, из
него же кадр к фото `otk-slayder`.

## Блок «Отказы парашюта»

Своих кадров отказов нет, поэтому взяты ролики со свободными лицензиями
с Wikimedia Commons, обрезанные под 4:3.

| Файл | Что на ролике | Лицензия | Автор | Источник |
|---|---|---|---|---|
| `otk-raskrytie` | нормальное раскрытие от вытяжного до купола | CC0 | SkydivePhoto | https://commons.wikimedia.org/wiki/File:Parachute_opening.webm |
| `otk-otcepka` | аварийный порядок: отказ, отцепка, раскрытие запасного | своё | Главпрыг, анимация | исходник `glavpryg-sayt/animaciya-otcepka.html` |
| `otk-otcepka-mob` | то же для телефона: сцена и надписи крупнее | своё | Главпрыг, анимация | тот же исходник с `?mob`; сборка `tools/animaciya-v-video.py --mob` |
| `otk-ruchka` | рывок кольца, показ на земле; на странице не стоит, файл оставлен | CC BY-SA 4.0 | Florentc59 | https://commons.wikimedia.org/wiki/File:Rescue_parachute_opening.ogg |
| `otk-dver` | запасной раскрылся у двери, Талли, 2025 (отрезок 34–54 с) | CC BY 4.0 | ATSB | https://commons.wikimedia.org/wiki/File:Premature_parachute_opening_over_Tully_Airport.webm |

### Фото к видам отказов

Файлы лежат в `public/images/otkazy/<имя>.webp`, формат 4:3, 800×600. Подпись выводится под фото.
Своих снимков отказов нет. Где снимка самого отказа под свободной лицензией не нашлось,
стоит поясняющий кадр, и подпись прямо говорит, что на нём.

| Файл | Вид отказа | Что на фото | Лицензия | Автор | Источник |
|---|---|---|---|---|---|
| `otk-zakrutka` | закрутка строп | настоящая закрутка | CC BY 2.0 | Richard Schneider | https://commons.wikimedia.org/wiki/File:Line_Twists_(6367630683).jpg |
| `otk-slayder` | купол не наполнился | кадр из ролика `otk-raskrytie`: середина раскрытия | CC0 | SkydivePhoto | https://commons.wikimedia.org/wiki/File:Parachute_opening.webm |
| `otk-klevanta` | клеванта | кадр из ролика `aff-kupol`: клеванты в руках | своё | Главпрыг | — |
| `otk-chastichnyy` | частичный отказ | купол остался в камере, основной на земле после отцепки | CC BY-SA 2.0 | stevenjbaker | https://www.flickr.com/photos/29808650@N06/3780438571 |
| `otk-polnyy` | полный отказ | вытяжной парашют при нормальном раскрытии | CC BY-SA 4.0 | Lawyerwebb | https://commons.wikimedia.org/wiki/File:Pilot_chute_inflated_bfore_collapse.jpg |
| `otk-dva` | два купола | настоящий случай, обрезан средний кадр серии | CC BY-SA 3.0 | Dmitry A. Mottl | https://commons.wikimedia.org/wiki/File:Malfunctioned_chute.jpg |
| `otk-dver-foto` | раскрытие у двери | кадр из ролика ATSB | CC BY 4.0 | ATSB | https://commons.wikimedia.org/wiki/File:Premature_parachute_opening_over_Tully_Airport.webm |
| `otk-zakrutka-2` | закрутка строп | настоящая закрутка сразу после раскрытия | CC BY-SA 3.0 | Greg Bulla | https://en.wikipedia.org/wiki/File:ParachuteTwist2.jpg |
| `otk-biplan` | два купола, «биплан» | показательная «этажерка» на авиашоу, не отказ (в подписи сказано) | CC BY-SA 4.0 | Sergei Kazantsev | https://commons.wikimedia.org/wiki/File:Этажерка.JPG |
| `otk-daunpleyn` | два купола, «даунплейн» | номер команды Leap Frogs, не отказ (в подписи сказано); 900×600, без обрезки | общественное достояние | U.S. Navy, Dave Kaylor | https://commons.wikimedia.org/wiki/File:US_Navy_070701-N-8110K-007_Two_members_of_the_Navy_Parachute_Team_Leap_Frogs_perform_their_trademark_downplane_maneuver_while_performing_for_the_first_time_in_history_at_Boston%27s_Fenway_Park.jpg |

### Ролики USPA (YouTube)

Учебная серия «Malfunctions» американской ассоциации парашютистов, список —
https://www.uspa.org/vrvideos. На сайт не копируются: встраиваются плеером
`youtube-nocookie.com`, который грузится только по нажатию; до этого видно
превью с `i.ytimg.com`. Встраивание разрешено владельцем (oEmbed отвечает 200).
Ролики на английском — в подписи сказано.

| Кадр в блоке | Ролик USPA | YouTube |
|---|---|---|
| Закрутка с вращением | 11 Line Twist | `GEqbTMRseik` |
| Перехлёст | 01 Line Over | `d1HmyO1-Xn8` |
| Купол не наполняется («колбаса») | 08 Streamer, Endless Snivel | `mweIHAETmNw` |
| Порыв купола и обрыв строп | 09 Torn Canopy and Broken Lines | `gS3t_MCYNV8` |
| Вытяжной лёг на купол | 10 Pilot Chute Over the Nose | `XlFgF_8NfaI` |
| Вытяжной в следе | 02 Pilot Chute in Tow | `nzu_QoUjy_M` |
| Купол не вышел из камеры | 03 Bag Lock | `8zYYkzqB62A` |
| «Подкова», которую освободили | 04 Horse Shoe clearable | `AE0zxm2f6Yk` |
| «Подкова», которую не освободить | 05 Horse Shoe unclearable | `YGh4pS7rokU` |
| Два купола: «биплан» | 06 Two Out biplane | `PodMf7JRsQU` |
| Два купола: «веер» | 07 Two Out side by side | `zZPoE4ry-4w` |

### Блок «Разборы» с вкладками

Стоит в секции «Отказы парашюта», после «Отказ: отцепка и запасной». Вкладки:
«Частичный» — 9 кадров, «Полный» — 4, «Особые случаи» — 9; снимки, свой ролик
`otk-dver` и ролики USPA. Под крупным кадром — подпись, источник и разбор
кадра: «Как выглядит», «Почему бывает», «Что делать».

Описания и порядок действий — по USPA SIM, раздел 5, и учебной серии USPA
«Malfunctions». Внизу блока об этом есть примечание: высота принятия решения
у USPA для учащихся — 760 м (2 500 футов); на прыжке действуют по порядку,
которому учит инструктор.

- **CC BY-SA 4.0:** обработанный ролик `otk-ruchka` распространяется на тех же
  условиях.
- **Разбор случая в Талли** пересказан по итоговому отчёту ATSB AO-2025-057:
  https://www.atsb.gov.au/investigations/ao-2025-057
- **Порядок действий в блоке** общий, по распространённой методике. Его нужно
  сверить с инструкторами Главпрыга: какие системы, где ручки, какие высоты,
  стоит ли страховочный фал.
