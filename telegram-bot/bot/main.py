"""Точка входа: опрос очереди обновлений и разбор того, что пришло.

Опрос длинными запросами (long polling), а не webhook. Причина простая: webhook
требует отдельного открытого наружу адреса с действующим сертификатом, а на
`46.8.178.196` уже стоит nginx с панелью по `/Claude` — добавлять туда ещё один
вход значит расширять то, что смотрит в сеть, ради задачи, которую опрос решает
бесплатно. Расход опроса — один висящий запрос.

Каждое обновление обрабатывается своей задачей, поэтому долгий ответ не
останавливает приём новых сообщений. Очередь внутри одного чата держит замок в
`engine`: два процесса движка на одной сессии разошлись бы в истории.
"""
import asyncio
import contextlib
import logging
import signal
import sys

from . import config, db, engine, fayly, zadachi
from .api import Bot, TelegramError, knopki

log = logging.getLogger("bot")

KOMANDY = [
    ("help", "что я умею"),
    ("new", "начать новый диалог"),
    ("projects", "выбрать проект"),
    ("task", "поставить задачу с утверждением"),
    ("tasks", "задачи и их состояние"),
    ("mode", "режим: делать сразу или с утверждением"),
    ("files", "файлы текущего проекта"),
    ("status", "что сейчас происходит"),
    ("stop", "прервать текущий ответ"),
    ("id", "показать мой Telegram id"),
]

SPRAVKA = """<b>Это второй пульт к тому же рабочему месту.</b>
Движок, база и история — те же, что в панели по адресу /Claude: начатое здесь
видно в браузере и продолжается там.

<b>Как работать</b>
• Просто напишите — отвечу в том диалоге, что сейчас выбран.
• /projects — выбрать проект. В проекте я вижу его каталог и правлю файлы.
• /mode — «сразу» или «с утверждением». Во втором любая просьба сперва
  возвращается замыслом с кнопками, и работа идёт только после «Утвердить».
• /task что сделать — поставить задачу отдельно, с утверждением, даже в режиме
  «сразу». /tasks — что утверждено, что идёт, что отклонено.
• Пришлите файл или снимок — положу в файлы проекта; снимок прогоню через
  распознавание и буду работать по тексту.
• /stop — прервать то, что я сейчас делаю. /status — что происходит и во что обошлось.

<b>Чего я не делаю</b>
Голос не разбираю — распознавателя речи на сервере нет. Картинку сам не вижу:
работаю по распознанному тексту, поэтому мелкий или рукописный кадр лучше
прислать получше."""

# Долгоживущие задачи обработки: без ссылок сборщик мусора вправе их убрать
_zadachi_obrabotki: set[asyncio.Task] = set()


# ---------------------------------------------------------------------------
# Доступ


async def dostup(bot: Bot, tg: dict, chat_id: int) -> bool:
    """Можно ли этому человеку писать боту.

    Права берутся из файла настроек при каждом обращении, а не из базы: иначе
    вычеркнутый из списка остался бы с правом, выданным когда-то раньше.
    """
    tg_id = int(tg.get("id") or 0)
    if not tg_id:
        # Сообщение без автора — канал или служебная запись. Отвечать некому,
        # а запись в tg_users с пустым ключом не завести.
        log.info("обновление без автора пропущено")
        return False

    mozhno = tg_id in config.ALLOWED_IDS
    zapis = await db.polzovatel(tg, allowed=mozhno)
    if mozhno:
        return True

    # Отвечаем на чужой стук не чаще раза в час: бот с угаданным именем собирает
    # перебор, и отвечать на каждый стук значит отвечать роботу.
    prezhniy = zapis.get("denied_at")
    teper = zapis.get("seychas")
    molcha = bool(prezhniy and teper and (teper - prezhniy).total_seconds() < 3600)
    if not molcha:
        await db.otkaz_otmetit(tg_id)
        await bot.send(
            chat_id,
            f"Доступ к этому боту не открыт.\nВаш Telegram id: <code>{tg.get('id')}</code>",
            html=True,
        )
        if config.ADMIN_ID and config.ADMIN_ID != tg.get("id"):
            with contextlib.suppress(TelegramError):
                await bot.send(
                    config.ADMIN_ID,
                    f"🔒 Стук в бота: <code>{tg.get('id')}</code> "
                    f"@{tg.get('username') or '—'} {tg.get('first_name') or ''}",
                    html=True,
                )
    log.warning("отказ: id=%s @%s", tg.get("id"), tg.get("username"))
    return False


# ---------------------------------------------------------------------------
# Текущий диалог


# Замок на завод диалога. Два сообщения подряд разбираются двумя задачами, и без
# него обе завели бы по своему диалогу: привязка досталась бы второму, а первый
# ответ ушёл бы в диалог, которого в чате уже нет.
_zamki_dialoga: dict[int, asyncio.Lock] = {}


async def tekushchiy_dialog(chat_id: int) -> dict:
    """Диалог, в котором идёт разговор. Нет — заводится чатик без проекта."""
    async with _zamki_dialoga.setdefault(chat_id, asyncio.Lock()):
        privyazka = await db.privyazka(chat_id)
        conv = None
        if privyazka.get("conversation_id"):
            conv = await db.dialog(privyazka["conversation_id"])
        if not conv:
            novyy = await db.novyy_dialog("Телеграм")
            await db.privyazat(chat_id, novyy["id"])
            conv = await db.dialog(novyy["id"])
        return conv


# ---------------------------------------------------------------------------
# Разбор обновления


async def obrabotat(bot: Bot, update: dict) -> None:
    try:
        if "callback_query" in update:
            await _knopka(bot, update["callback_query"])
        elif "message" in update:
            await _soobshchenie(bot, update["message"])
    except Exception:                                   # noqa: BLE001
        log.exception("сбой при разборе обновления %s", update.get("update_id"))


async def _soobshchenie(bot: Bot, message: dict) -> None:
    tg = message.get("from") or {}
    chat_id = (message.get("chat") or {}).get("id")
    if not chat_id or not await dostup(bot, tg, chat_id):
        return

    text = (message.get("text") or message.get("caption") or "").strip()

    # Вложение: сохранить, распознать и приложить к просьбе
    soprovod = None
    if message.get("document") or message.get("photo") or message.get("voice") \
            or message.get("audio") or message.get("video_note"):
        conv = await tekushchiy_dialog(chat_id)
        soprovod = await fayly.prinyat(bot, chat_id, message, conv)
        if soprovod is None:
            return
        text = f"{soprovod}\n\n{text}" if text else (
            f"{soprovod}\n\nРазберись, что с этим делать, и скажи, что предлагаешь."
        )

    if not text:
        return

    # Ждём уточнения к задаче — тогда это оно, а не новая просьба
    if (task_id := zadachi.zhdet_utochneniya(chat_id)) and not text.startswith("/"):
        await zadachi.utochnit(bot, chat_id, task_id, text)
        return

    if text.startswith("/"):
        await _komanda(bot, chat_id, tg, text)
        return

    privyazka = await db.privyazka(chat_id)
    conv = await tekushchiy_dialog(chat_id)

    # Режим «с утверждением»: сперва замысел и кнопки, работа — после «Утвердить»
    if privyazka.get("mode") == "plan" and conv.get("project_id"):
        await zadachi.postavit(bot, chat_id, tg.get("id"), text)
        return

    pervoe = conv.get("title") == "Телеграм"
    itog = await engine.otvetit(bot, chat_id, conv, text)
    if itog and pervoe:
        # Название по первой реплике — отдельным дешёвым вызовом, в стороне:
        # «Телеграм» через неделю в списке диалогов ничего не говорит
        _v_storone(engine.nazvat(conv["id"], text))


async def _komanda(bot: Bot, chat_id: int, tg: dict, text: str) -> None:
    chasti = text.split(maxsplit=1)
    imya = chasti[0].lstrip("/").split("@")[0].lower()
    hvost = chasti[1].strip() if len(chasti) > 1 else ""

    if imya in ("start", "help"):
        await bot.send(chat_id, SPRAVKA, html=True)
        await _kto_ya(bot, chat_id)

    elif imya == "id":
        await bot.send(
            chat_id,
            f"Ваш Telegram id: <code>{tg.get('id')}</code>\n"
            f"Доступ: {'открыт' if int(tg.get('id') or 0) in config.ALLOWED_IDS else 'нет'}",
            html=True,
        )

    elif imya == "new":
        conv = await tekushchiy_dialog(chat_id)
        project_id = conv.get("project_id")
        novyy = await db.novyy_dialog("Телеграм", project_id)
        await db.privyazat(chat_id, novyy["id"])
        gde = f" в проекте «{conv['project_name']}»" if project_id else ""
        await bot.send(chat_id, f"Начат новый диалог{gde}. Прежний цел — он в панели.")

    elif imya == "projects":
        await _proekty(bot, chat_id)

    elif imya == "mode":
        privyazka = await db.privyazka(chat_id)
        seychas = "сразу" if privyazka.get("mode") == "srazu" else "с утверждением"
        await bot.send(
            chat_id,
            f"Сейчас: <b>{seychas}</b>.\n\n"
            "«Сразу» — делаю, как написано. «С утверждением» — любая просьба по "
            "проекту сперва возвращается замыслом, и работа идёт только после "
            "нажатия «Утвердить».",
            html=True,
            markup=knopki([[("Сразу", "m:srazu"), ("С утверждением", "m:plan")]]),
        )

    elif imya == "task":
        if not hvost:
            await bot.send(chat_id, "Напишите задачу после команды: "
                                    "<code>/task поправить шапку на странице услуг</code>",
                           html=True)
            return
        await zadachi.postavit(bot, chat_id, tg.get("id"), hvost)

    elif imya == "tasks":
        await zadachi.spisok(bot, chat_id)

    elif imya == "files":
        await fayly.spisok(bot, chat_id, await tekushchiy_dialog(chat_id))

    elif imya == "status":
        await _svodka(bot, chat_id)

    elif imya == "stop":
        if engine.ostanovit(chat_id):
            await bot.send(chat_id, "Прерываю…")
        else:
            await bot.send(chat_id, "Сейчас ничего не выполняется.")

    else:
        await bot.send(chat_id, "Такой команды нет. Что умею — /help")


async def _kto_ya(bot: Bot, chat_id: int) -> None:
    conv = await tekushchiy_dialog(chat_id)
    privyazka = await db.privyazka(chat_id)
    gde = f"проект «{conv['project_name']}»" if conv.get("project_id") else "разговор без проекта"
    rezhim = "сразу" if privyazka.get("mode") == "srazu" else "с утверждением"
    await bot.send(chat_id, f"Сейчас: {gde}, режим «{rezhim}», диалог «{conv['title']}».")


async def _proekty(bot: Bot, chat_id: int) -> None:
    proekty = await db.proekty()
    conv = await tekushchiy_dialog(chat_id)
    ryady = []
    for proekt in proekty:
        otmetka = "• " if proekt["id"] == conv.get("project_id") else ""
        zamok = " 🔑" if proekt.get("allow_bash") else ""
        ryady.append([(f"{otmetka}{proekt['name']}{zamok}", f"p:{proekt['id']}")])
    ryady.append([("Без проекта — просто разговор", "p:0")])
    if not proekty:
        await bot.send(
            chat_id,
            "Проектов в базе нет. Завести их можно в панели: /Claude → «Проекты». "
            "Без проекта я отвечаю, но файлы не трогаю.",
        )
        return
    await bot.send(
        chat_id,
        "В каком проекте работать? 🔑 — проекту разрешён запуск команд.",
        markup=knopki(ryady),
    )


async def _svodka(bot: Bot, chat_id: int) -> None:
    conv = await tekushchiy_dialog(chat_id)
    privyazka = await db.privyazka(chat_id)
    rashod = await db.rashod_za_sutki()
    zhdut = await db.zadachi(limit=50, status="waiting")

    stroki = [
        f"<b>Диалог:</b> {conv['title']} (#{conv['id']})",
        f"<b>Проект:</b> {conv.get('project_name') or '—'}",
        f"<b>Режим:</b> {'сразу' if privyazka.get('mode') == 'srazu' else 'с утверждением'}",
        f"<b>Контекст темы:</b> {conv.get('context_tokens') or 0:,}".replace(",", " ") + " ток.",
        f"<b>Сейчас:</b> {'идёт ответ' if engine.zanyato(chat_id) else 'свободна'}",
        f"<b>За сутки:</b> {rashod['otvetov']} ответов, "
        + f"{int(rashod['tokenov']):,}".replace(",", " ") + " ток., "
        + f"${float(rashod['stoimost']):.2f}",
        f"<b>Ждут утверждения:</b> {len(zhdut)}",
    ]
    await bot.send(chat_id, "\n".join(stroki), html=True)


async def _knopka(bot: Bot, cq: dict) -> None:
    tg = cq.get("from") or {}
    chat_id = ((cq.get("message") or {}).get("chat") or {}).get("id")
    data = cq.get("data") or ""
    if not chat_id or not await dostup(bot, tg, chat_id):
        await bot.answer_callback(cq["id"], "Доступ не открыт")
        return

    if data.startswith("p:"):
        await _vybrat_proekt(bot, chat_id, cq["id"], int(data[2:]))

    elif data.startswith("m:"):
        rezhim = data[2:]
        await db.rezhim(chat_id, rezhim if rezhim in ("srazu", "plan") else "srazu")
        await bot.answer_callback(cq["id"], "Готово")
        await bot.send(
            chat_id,
            "Режим: " + ("делаю сразу." if rezhim == "srazu" else
                         "сперва замысел, работа — после «Утвердить»."),
        )

    elif data.startswith("t:"):
        if data.endswith(":again"):
            await zadachi.povtorit(bot, chat_id, cq["id"], int(data.split(":")[1]))
        else:
            await zadachi.reshenie(bot, chat_id, cq["id"], data)

    elif data.startswith("f:"):
        await fayly.otdat(bot, chat_id, cq["id"], int(data[2:]))

    else:
        await bot.answer_callback(cq["id"], "Кнопка устарела")


async def _vybrat_proekt(bot: Bot, chat_id: int, callback_id: str, project_id: int) -> None:
    if project_id == 0:
        novyy = await db.novyy_dialog("Телеграм")
        await db.privyazat(chat_id, novyy["id"])
        await bot.answer_callback(callback_id, "Без проекта")
        await bot.send(chat_id, "Работаю без проекта: отвечаю, файлы не трогаю.")
        return

    proekt = await db.proekt(project_id)
    if not proekt:
        await bot.answer_callback(callback_id, "Проект не найден")
        return

    # Берём свежую тему проекта, а не заводим новую: иначе каждое переключение
    # плодило бы пустые темы и теряло контекст работы
    tema = await db.posledniy_dialog(project_id)
    if not tema:
        tema = await db.novyy_dialog(f"Телеграм: {proekt['name']}", project_id)
    await db.privyazat(chat_id, tema["id"])

    await bot.answer_callback(callback_id, proekt["name"])
    prava = "команды разрешены" if proekt["allow_bash"] else "команды запрещены"
    await bot.send(
        chat_id,
        f"Проект «{proekt['name']}», тема «{tema['title']}».\n"
        f"Каталог: <code>{proekt['workdir']}</code>, {prava}.",
        html=True,
    )


def _v_storone(coro) -> None:
    """Пустить сопутствующую работу рядом, не задерживая ответ."""
    zadacha = asyncio.create_task(coro)
    _zadachi_obrabotki.add(zadacha)
    zadacha.add_done_callback(_zadachi_obrabotki.discard)


# ---------------------------------------------------------------------------
# Опрос очереди


async def opros(bot: Bot) -> None:
    smeshchenie = await db.smeshchenie()
    log.info("опрос с смещения %s", smeshchenie)
    sboev = 0
    while True:
        try:
            obnovleniya = await bot.get_updates(smeshchenie or None)
            sboev = 0
        except asyncio.CancelledError:
            raise
        except Exception as error:                      # noqa: BLE001
            sboev += 1
            pauza = min(60, 2 ** min(sboev, 6))
            log.warning("опрос не удался (%s), повтор через %s с", error, pauza)
            await asyncio.sleep(pauza)
            continue

        for obnovlenie in obnovleniya:
            smeshchenie = int(obnovlenie["update_id"]) + 1
            # Смещение двигается до обработки, а не после. Иначе долгая задача,
            # прерванная перезапуском службы, приехала бы заново и выполнилась
            # второй раз — а это правки в файлах и коммиты.
            _v_storone(obrabotat(bot, obnovlenie))

        if obnovleniya:
            await db.smeshchenie_zapisat(smeshchenie)


async def zapustit() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)

    await db.init()
    bot = Bot(config.TOKEN)

    try:
        ya = await bot.me()
    except Exception as error:                          # noqa: BLE001
        log.error("Телеграм не принял токен: %s", error)
        await bot.close()
        await db.close()
        raise

    log.info("бот @%s запущен, разрешённых собеседников: %s",
             ya.get("username"), len(config.ALLOWED_IDS))
    if not config.ALLOWED_IDS:
        log.warning("список TELEGRAM_ALLOWED пуст — бот не ответит никому. "
                    "Свой id покажет команда /id.")
    await bot.set_commands(KOMANDY)

    rabota = asyncio.create_task(opros(bot))

    # Останов по сигналу: systemd гасит службу SIGTERM, и без этого она умирала
    # бы посреди ответа, не закрыв ни пул, ни соединение с Телеграмом
    cikl = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            cikl.add_signal_handler(sig, rabota.cancel)

    with contextlib.suppress(asyncio.CancelledError):
        await rabota

    log.info("останов")
    await bot.close()
    await db.close()


def main() -> None:
    try:
        asyncio.run(zapustit())
    except KeyboardInterrupt:
        pass
    except TelegramError as error:
        # Запустившему руками нужна строка, а не стенограмма вызовов: почти
        # всегда это незаполненный или перепутанный токен в файле настроек,
        # и подсказать надо путь к нему, а не место в коде.
        print(f"Телеграм отказал: {error}", file=sys.stderr)
        print(f"Проверьте TELEGRAM_TOKEN в {config.ENV_FILE}", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
