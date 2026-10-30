# Конструктор анимированных 3D-моделей

**Сейчас (с 30.10.2026) работает на нашем сервере:** редактор —
https://mokeevasky.ru/Claude/v2/3d/ (вкладка «3D» сайта, его вход и замок, код —
`webui2/app/konstruktor.py`, хранилище — `~/.local/share/konstruktor3d`), просмотрщик —
https://mokeevasky.ru/glavpryg/model-3d/parashyutnaya-sistema/. Выложить новый просмотрщик:
экспорт в `prosmotrshchik/public/index.html`, копия с `.gz` в каталог сайта
(права файлов 0640, каталогу chmod не делать). Проверка под входом — `proverki/sayt-stend.py`
(временный сайт, настоящий не трогает) и `bez-ii-test.mjs` с `ADRES` и `KUKA`.

Ниже — устройство и вариант для переезда в Cloudflare, когда убедимся, что всё работает.

Два отдельных проекта Cloudflare — их нельзя смешивать, закрытый вход действует
на весь адрес.

| Папка | Что это | Адрес |
|---|---|---|
| `redaktor/` | закрытый редактор: страницы, хранилище, обращения к ИИ | 3d.mokeevasky.ru, вход по Access |
| `prosmotrshchik/` | открытый просмотрщик одной модели | model.mokeevasky.ru |
| `proverki/` | автоматические проверки (не выкладываются) | — |

## Устройство

- `redaktor/public/dvizhok/` — движок показа. Один и тот же код в редакторе,
  в «Предпросмотре» и в выгруженном просмотрщике:
  - `format.js` — формат описания и его проверка (им же пользуется сервер);
  - `dvizhok.js` — сцена, формы, вложенность, взрыв-схема, номера, таблица, анимации;
  - `eksport.js` — сборка автономной страницы одной модели в один HTML-файл.
- `redaktor/public/modeli/*.json` — модели-образцы. Новая модель — новый файл,
  движок не трогается. Список образцов — `modeli/spisok.json`.
- `redaktor/public/vendor/` — three.js 0.186.1 одним файлом (вместе с OrbitControls)
  и GLTFExporter; пересборка — esbuild из npm-пакета `three`, MIT (`THREE-LICENSE.txt`).
- `redaktor/src/` — серверная функция:
  - `dostup.js` — проверка пропуска Cloudflare Access на каждом запросе
    (страницы тоже); без настроенного Access не пускает никого;
  - `worker.js` — хранилище моделей и фото (KV), лимиты, обращения к ИИ;
  - `ii.js` — запросы к Claude: фото уходят как файлы (Files API, 90 дней),
    ответ — описание модели, проверяется `format.js`, при ошибках — одна попытка исправить.
- Внешний ИИ выключен: `AI_ENABLED` в `redaktor/wrangler.jsonc` равно `0`, сервер отказывает
  даже при наличии ключа, кнопки скрыты. Модели составляет Claude в «Проектах».
  Если включать: ключ — только секрет Cloudflare `ANTHROPIC_API_KEY`; модель и усилие —
  `AI_MODEL`, `AI_EFFORT`.

## Формат описания (кратко)

`name`, `scale.text` (один реальный размер), `view` (камера), `parts[]`
(`id`, `num`, `name`, `desc`, `parent`, `shape`, `color`, `position`, `rotation`,
`scale`, `label`, `anchors`, `explode {dir, dist}`), `animations[]`
(`id`, `name`, `type`, `target`, `autoplay`, `params`). Метры, Y вверх, перед — +Z,
правый борт — −X. Точки — в общих координатах собранной модели. Полный список
форм и анимаций — в `format.js`.

## Локальный запуск

```
cd redaktor
npm install
cp .dev.vars.primer .dev.vars      # LOCAL_DEV=1 — пускает только с этого компьютера
npx wrangler dev --port 8787 --ip 127.0.0.1
```

Без сервера редактор тоже открывается (любой статический сервер из `redaktor/public`):
тогда сохранение — в браузере, создание по фото недоступно.

Экспорт из командной строки (то же, что кнопка):
`node instrumenty/eksport.mjs public/modeli/parashyut.json ../prosmotrshchik/public/index.html`

## Проверки

Нужны запущенные: редактор на 8787 (с заглушкой ИИ: `ANTHROPIC_BASE_URL=http://127.0.0.1:8799`
в `.dev.vars`, `node proverki/zaglushka-ii.mjs`), просмотрщик на 8788, статический сервер
из `konstruktor/` на 8765.

- `redaktor-test.mjs` — показ, выбор в обе стороны, правка, сохранение, предпросмотр,
  экспорт, создание по фото и правка словами, ключ не виден в браузере;
- `prosmotrshchik-test.mjs` — просмотрщик по ссылке и внутри чужой страницы;
- `sravnenie-test.mjs` — предпросмотр и выложенный файл совпадают байт в байт;
- `dostup-test.mjs` — пропуск Access: настоящий, поддельный, чужой, просроченный;
- `fayly-test.mjs` — GLB и видео;
- `bez-ii-test.mjs` — ИИ выключен: нет кнопок, сервер отказывает, запросов к ИИ нет;
  фото и экспорты хранятся. `redaktor-test.mjs` — при `AI_ENABLED=1` в `.dev.vars`.

## Размещение

Нужны: включённый Zero Trust, идентификатор аккаунта (`CLOUDFLARE_ACCOUNT_ID`) и ключ с правами:
аккаунт — Workers Scripts, Workers KV Storage, Access: Apps and Policies, Access: Organizations,
Identity Providers, and Groups (все Edit), Account Settings (Read); зона mokeevasky.ru —
Workers Routes (Edit), Zone (Read).

1. `npx wrangler kv namespace create HRAN` → id в `redaktor/wrangler.jsonc`.
2. Access: вход по коду на почту, приложение на `3d.mokeevasky.ru`, политика «почта из списка»;
   адрес команды и AUD → `ACCESS_TEAM_DOMAIN`, `ACCESS_AUD`.
3. `npx wrangler deploy` в `redaktor/` и в `prosmotrshchik/`.
4. Проверить вживую: почта из списка, чужая почта, поддельный и просроченный пропуски;
   запрос без входа, служебный адрес workers.dev выключен; приём фото и экспортов в хранилище.
