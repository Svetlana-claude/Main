# Конструктор анимированных 3D-моделей

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
- Ключ ИИ — только секрет Cloudflare `ANTHROPIC_API_KEY`. Модель и усилие —
  переменные `AI_MODEL`, `AI_EFFORT` в `redaktor/wrangler.jsonc`.

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
- `fayly-test.mjs` — GLB и видео.

## Размещение (когда будет ключ Cloudflare)

1. KV: `npx wrangler kv namespace create HRAN` → id в `redaktor/wrangler.jsonc`.
2. Zero Trust → Access → приложение на `3d.mokeevasky.ru`, политика «почта из списка»;
   адрес команды и AUD → `ACCESS_TEAM_DOMAIN`, `ACCESS_AUD`.
3. `npx wrangler deploy` в `redaktor/` и в `prosmotrshchik/`.
4. Ключ ИИ вносит владелец: `npx wrangler secret put ANTHROPIC_API_KEY` или в панели.
5. Проверить вживую: без входа — 403 и страница Access; workers.dev выключен.
