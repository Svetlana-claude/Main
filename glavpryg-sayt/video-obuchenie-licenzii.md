# Ролики страницы «Обучение» — откуда и на каких условиях

Страница `resources/views/services/obuchenie.blade.php`, ролики —
`public/video/<имя>.mp4` и обложка `<имя>.jpg`, кадр 4:3, 960×720, без звука.
Подпись автора и лицензии выводится под роликом (шаблон `partials/rolik.blade.php`).

## Блок «Как пройти обучение»

Своя съёмка Главпрыга, подпись не нужна.

| Файл | Что на ролике | Откуда |
|---|---|---|
| `aff-otdelenie` | дверь самолёта, отделение | ролик тандема, 13–23 с |
| `aff-padenie` | свободное падение | ролик тандема, 28–37 с |
| `aff-kupol` | раскрытие и купол, вид от первого лица | ролик самостоятельного прыжка, 15,5–23 с |

## Блок «Отказы парашюта»

Своих кадров отказов нет, поэтому взяты ролики со свободными лицензиями
с Wikimedia Commons, обрезанные под 4:3.

| Файл | Что на ролике | Лицензия | Автор | Источник |
|---|---|---|---|---|
| `otk-raskrytie` | нормальное раскрытие от вытяжного до купола | CC0 | SkydivePhoto | https://commons.wikimedia.org/wiki/File:Parachute_opening.webm |
| `otk-ruchka` | рывок кольца, показ на земле, замедлен в 1,5 раза | CC BY-SA 4.0 | Florentc59 | https://commons.wikimedia.org/wiki/File:Rescue_parachute_opening.ogg |
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

- **CC BY-SA 4.0:** обработанный ролик `otk-ruchka` распространяется на тех же
  условиях.
- **Разбор случая в Талли** пересказан по итоговому отчёту ATSB AO-2025-057:
  https://www.atsb.gov.au/investigations/ao-2025-057
- **Порядок действий в блоке** общий, по распространённой методике. Его нужно
  сверить с инструкторами Главпрыга: какие системы, где ручки, какие высоты,
  стоит ли страховочный фал.
