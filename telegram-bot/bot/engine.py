"""Запуск движка и живой показ хода работы.

Движок — тот же `claude_driver`, что у веб-интерфейса: Claude Code в
неинтерактивном режиме. Бот не обращается к Messages API и не заводит своих
правил доступа — права темы проекта определяет та же запись в базе
(`projects.allow_bash`, рабочий каталог), что и в браузере.

Что добавляет этот модуль:

* **одно сообщение «Ход работы»**, которое правится по мере ответа, — вместо
  потока сообщений, который Телеграм отобьёт по частоте;
* **один ответ за раз на чат**: вторая просьба ждёт замка, а не запускает рядом
  второй процесс движка на той же сессии (`--resume` одной сессии двумя
  процессами разошёлся бы в истории);
* **возврат разметки на отбой**: если Телеграму не понравился HTML, кусок уходит
  без тегов. Потерять оформление лучше, чем потерять ответ.
"""
import asyncio
import logging
import time
from pathlib import Path

from app.services import claude_driver

from . import config, db, razmetka
from .api import Bot, TelegramError

log = logging.getLogger("bot.engine")

KRUTILKA = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

# Замок на чат: один ответ за раз. Очередь честная — asyncio.Lock отдаёт замок
# в порядке ожидания, поэтому две просьбы подряд выполнятся в том же порядке.
_zamki: dict[int, asyncio.Lock] = {}
# Текущая работа по чату — её снимает /stop
_raboty: dict[int, asyncio.Task] = {}


def _zamok(chat_id: int) -> asyncio.Lock:
    return _zamki.setdefault(chat_id, asyncio.Lock())


def zanyato(chat_id: int) -> bool:
    return _zamok(chat_id).locked()


def ostanovit(chat_id: int) -> bool:
    """Снять выполняющийся ответ. Процесс движка гасит `finally` в драйвере."""
    rabota = _raboty.get(chat_id)
    if rabota and not rabota.done():
        rabota.cancel()
        return True
    return False


async def otvetit(bot: Bot, chat_id: int, conv: dict, prompt: str) -> dict | None:
    """Ответить на просьбу в рамках диалога. Возвращает итог или None при сбое."""
    zamok = _zamok(chat_id)
    if zamok.locked():
        await bot.send(chat_id, "⏳ Дописываю предыдущий ответ — эта просьба следующая.")
    async with zamok:
        _raboty[chat_id] = asyncio.current_task()
        try:
            return await _progon(bot, chat_id, conv, prompt)
        except asyncio.CancelledError:
            # Прерывание своё, по /stop. Сообщить о нём надо: иначе «Ход работы»
            # останется висеть последней правкой, как будто ответ ещё идёт.
            try:
                await db.soobshchenie_oshibki(conv["id"], "Прервано по /stop")
                await bot.send(chat_id, "⏹ Прервано.")
            except Exception:
                pass
            return None
        except Exception as error:                      # noqa: BLE001
            log.exception("сбой при ответе в чате %s", chat_id)
            try:
                await bot.send(chat_id, razmetka.soobshchit_oshibku(
                    f"Сбой бота: {error}. Подробности — в журнале службы."))
            except Exception:
                pass
            return None
        finally:
            _raboty.pop(chat_id, None)


async def _progon(bot: Bot, chat_id: int, conv: dict, prompt: str) -> dict | None:
    # Диалог перечитывается ЗДЕСЬ, после замка, а не берётся снимком от
    # вызывающей стороны. Два сообщения подряд в новом диалоге разбираются
    # двумя задачами, и у второй в снимке ещё нет `claude_session_id`: без
    # перечитывания она запустила бы вторую сессию Claude Code вместо
    # продолжения первой, и история в теме разошлась бы с историей движка.
    svezhiy = await db.dialog(conv["id"])
    if svezhiy:
        conv = svezhiy

    nastroyki = await db.nastroyki()
    model = nastroyki.get("model") or "opus"
    okno = claude_driver.compact_window(nastroyki.get("compact_window"))

    s_instrumentami = conv.get("kind") == "topic"
    workdir = Path(conv["workdir"]) if conv.get("workdir") else None
    allow_bash = bool(conv.get("allow_bash"))

    await db.soobshchenie_polzovatelya(conv["id"], prompt)

    hod = await bot.send(chat_id, "⏳ Принято, думаю…")
    hod_id = hod["message_id"]

    tekst = ""
    instrumenty: list[str] = []
    itog: dict | None = None
    oshibka: str | None = None
    nachalo = time.monotonic()
    pravka = 0.0
    shag = 0

    async def pokazat(force: bool = False) -> None:
        """Правка «Хода работы». Чаще EDIT_INTERVAL_SEC Телеграм отобьёт по частоте."""
        nonlocal pravka, shag
        teper = time.monotonic()
        if not force and teper - pravka < config.EDIT_INTERVAL_SEC:
            return
        pravka = teper
        shag += 1
        stroka = f"{KRUTILKA[shag % len(KRUTILKA)]} {int(teper - nachalo)} с"
        if instrumenty:
            stroka += " · " + ", ".join(list(dict.fromkeys(instrumenty))[-3:])
        hvost = razmetka.prostoy(tekst, config.TAIL_CHARS)
        await bot.edit(chat_id, hod_id, stroka + (f"\n\n{hvost}" if hvost else ""))
        await bot.action(chat_id)        # «печатает…» живёт 5 с, поэтому повторяется

    async for event in claude_driver.run(
        prompt,
        model=model,
        session_id=conv.get("claude_session_id"),
        with_tools=s_instrumentami,
        workdir=workdir,
        allow_bash=allow_bash,
        compact_window=okno,
    ):
        tip = event.get("type")

        if tip == "delta":
            tekst += event.get("text") or ""
            await pokazat()

        elif tip == "text":
            # Полный текст очередного сообщения: заменяет накопленное из кусков
            tekst = event.get("text") or tekst

        elif tip == "tool":
            instrumenty.append(_imya_instrumenta(event))
            await pokazat(force=True)    # инструменты редки, их видно сразу

        elif tip == "compact":
            # Сжатие идёт десятки секунд без единого другого события: без этой
            # строки «Ход работы» выглядел бы зависшим
            if event.get("state") == "start":
                await bot.edit(chat_id, hod_id, "🗜 Сжимаю контекст…")
                pravka = time.monotonic()
            elif event.get("state") == "failed":
                log.info("сжатие отклонено: %s", event.get("reason"))

        elif tip == "result":
            itog = event

        elif tip == "error":
            oshibka = event.get("message")

    if itog and not itog.get("is_error") and not oshibka:
        await db.soobshchenie_otveta(conv["id"], itog)
        await _vylozhit(bot, chat_id, itog.get("text") or tekst)
        svodka = razmetka.svodka(itog)
        await bot.edit(chat_id, hod_id, "🏁 " + (svodka or "готово"))
        return itog

    soobshchenie = oshibka or (itog or {}).get("error_message") or "движок не ответил"
    hvost = (itog or {}).get("text") or ""
    if hvost and hvost not in soobshchenie:
        soobshchenie = f"{soobshchenie}\n\n{hvost}"
    await db.soobshchenie_oshibki(conv["id"], soobshchenie)
    await bot.edit(chat_id, hod_id, razmetka.soobshchit_oshibku(soobshchenie))
    return None


async def _vylozhit(bot: Bot, chat_id: int, text: str, markup: dict | None = None) -> None:
    """Ответ сообщениями по 3500 знаков. Кнопки — только под последним."""
    kuski = razmetka.narezat(text, config.CHUNK_LIMIT) or ["(пустой ответ)"]
    for nomer, kusok in enumerate(kuski):
        posledniy = nomer == len(kuski) - 1
        knopki = markup if posledniy else None
        try:
            await bot.send(chat_id, razmetka.v_html(kusok), html=True, markup=knopki)
        except TelegramError as error:
            # Телеграм разбирает теги сам и на непонятном отказывается отправлять
            # сообщение целиком. Тогда — без разметки: оформление дешевле ответа.
            log.warning("разметка отбита (%s), отправляю без тегов", error.description)
            await bot.send(chat_id, kusok[:4000], markup=knopki)
        if not posledniy:
            await asyncio.sleep(0.4)     # пачку сообщений подряд Телеграм отбивает


def _imya_instrumenta(event: dict) -> str:
    """Название инструмента с коротким пояснением: что именно он делает."""
    name = event.get("name") or "?"
    vhod = event.get("input") or {}
    if not isinstance(vhod, dict):
        return name
    for klyuch in ("file_path", "path", "pattern", "command", "url", "description"):
        znachenie = vhod.get(klyuch)
        if isinstance(znachenie, str) and znachenie.strip():
            korotko = znachenie.strip().split("\n")[0]
            if klyuch in ("file_path", "path"):
                korotko = korotko.rsplit("/", 1)[-1]
            return f"{name} {korotko[:40]}"
    return name


async def sprosit(prompt: str, model: str = "haiku") -> str:
    """Короткий вопрос движку без инструментов и без записи в базу.

    Этим собираются замысел задачи и названия диалогов: такие вызовы не часть
    разговора, и в истории им делать нечего.
    """
    otvet = ""
    async for event in claude_driver.run(prompt, model=model, with_tools=False):
        if event.get("type") == "result":
            if event.get("is_error"):
                return ""
            otvet = event.get("text") or ""
    return otvet.strip()


async def nazvat(conversation_id: int, pervoe: str) -> None:
    """Дать диалогу название по первой реплике. Запускается в стороне от ответа."""
    try:
        title = await claude_driver.make_title(pervoe)
        await db.pereimenovat(conversation_id, title)
    except Exception:                                   # noqa: BLE001
        log.warning("не удалось назвать диалог %s", conversation_id, exc_info=True)
