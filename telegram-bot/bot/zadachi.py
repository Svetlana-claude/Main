"""Задачи: постановка → замысел → утверждение кнопкой → работа → итог.

Зачем отдельная сущность, если можно просто написать боту просьбу. Потому что у
просьбы нет двух вещей, которые нужны в работе по проектам:

* **решения.** Между «я написала, что надо сделать» и «делай» должен быть шаг, на
  котором видно, как просьбу понял исполнитель. Замысел показывается до работы, а
  не после, — и утверждается кнопкой;
* **состояния.** Утверждённое, идущее и отклонённое надо видеть списком через
  неделю, а не искать в переписке.

⚠️ **Замысел составляется без инструментов** — это переформулировка просьбы, а не
изучение кода: заглядывать в файлы на этом шаге нельзя, потому что инструменты
правки включаются вместе с чтением, и «только посмотреть» не бывает. Изучение кода
начинается после утверждения.
"""
import logging

from . import db, engine, razmetka
from .api import Bot, knopki

log = logging.getLogger("bot.zadachi")

# Какой моделью переформулировать. Опус на эту работу не нужен: нужна связная
# выжимка из уже написанного, а не рассуждение.
MODEL_ZAMYSLA = "sonnet"

ZAPROS_ZAMYSLA = """Ниже — задача, поставленная заказчиком своими словами.
Переформулируй её так, чтобы было видно, как ты её понял, и чтобы заказчик мог
утвердить это нажатием кнопки. Ответь строго по образцу, без вступлений:

ЗАГОЛОВОК: короткое название задачи, до 60 знаков

Что сделаю:
1. …
2. …
(от двух до шести пунктов, каждый — проверяемое действие)

Что изменится: какие файлы или страницы затронет, одной-двумя строками.

Чем рискую: чего может не хватить или что может пойти не так, одной-двумя
строками. Если ничего существенного — так и напиши.

Если в задаче чего-то не хватает для работы, добавь раздел
«Нужно уточнить:» со списком вопросов.

Не выполняй задачу и не предлагай код. Отвечай по-русски.

Проект: {proekt}
Задача:
{zadacha}"""

ZAPROS_RABOTY = """Задача утверждена заказчиком. Выполни её целиком.

Задача: {title}

Как поставлена:
{body}

Утверждённый замысел:
{plan}
{note}
Работай по правилам из CLAUDE.md: до работы запись в log.md, по завершении —
коммит и запись в result.md. В конце ответь коротко: что сделано, что проверено,
чего сделать не удалось."""

# Каких задач бот ждёт уточнения. В памяти: ожидание живёт минуты, и держать его
# в базе ради перезапуска незачем — после перезапуска задача просто ставится заново.
_zhdut_utochneniya: dict[int, int] = {}     # chat_id -> task_id


def zhdet_utochneniya(chat_id: int) -> int | None:
    return _zhdut_utochneniya.get(chat_id)


def zabyt_utochnenie(chat_id: int) -> None:
    _zhdut_utochneniya.pop(chat_id, None)


def _klaviatura(task_id: int) -> dict:
    return knopki([[
        ("✅ Утвердить", f"t:{task_id}:ok"),
        ("✏️ Уточнить", f"t:{task_id}:re"),
        ("❌ Отклонить", f"t:{task_id}:no"),
    ]])


# Сколько замысла показывать. Урезается ИСХОДНЫЙ Markdown, а не готовый HTML:
# обрезка HTML по знакам рассекает тег, и Телеграм отказывается отправлять
# сообщение целиком — замысел пропал бы весь.
PREDEL_ZAMYSLA = 2500


async def _pokazat(
    bot: Bot, chat_id: int, task_id: int, title: str, telo: str, pometka: str = ""
) -> None:
    """Показать замысел с кнопками и запомнить сообщение, под которым они стоят."""
    if len(telo) > PREDEL_ZAMYSLA:
        telo = telo[:PREDEL_ZAMYSLA] + "\n\n… (полностью — в панели /Claude)"
    shapka = f"<b>Задача {task_id}: {_bezopasno(title)}</b>"
    if pometka:
        shapka += f" {_bezopasno(pometka)}"
    otpravleno = await bot.send(
        chat_id, f"{shapka}\n\n{razmetka.v_html(telo)}",
        html=True, markup=_klaviatura(task_id),
    )
    await db.zadacha_soobshchenie(task_id, otpravleno["message_id"])


def _razobrat(zamysel: str, zapas: str) -> tuple[str, str]:
    """Отделяет заголовок от остального. Нет заголовка — берём начало постановки."""
    title = ""
    stroki = (zamysel or "").split("\n")
    telo = []
    for nomer, stroka in enumerate(stroki):
        if not title and stroka.strip().upper().startswith("ЗАГОЛОВОК:"):
            title = stroka.split(":", 1)[1].strip().strip("*").strip()
            telo = stroki[nomer + 1:]
            break
    else:
        telo = stroki
    if not title:
        title = " ".join(zapas.split())[:60]
    return title[:200], "\n".join(telo).strip()


async def postavit(bot: Bot, chat_id: int, tg_id: int, text: str) -> None:
    """Поставить задачу: завести запись, составить замысел, показать с кнопками."""
    privyazka = await db.privyazka(chat_id)
    conv = await db.dialog(privyazka["conversation_id"]) if privyazka["conversation_id"] else None
    project_id = conv.get("project_id") if conv else None

    if not project_id:
        await bot.send(
            chat_id,
            "Задача ставится по проекту, а проект не выбран: нажмите /projects и "
            "выберите, в каком каталоге работать. Без проекта движок не получит "
            "доступа к файлам, и утверждать было бы нечего.",
        )
        return

    proekt = await db.proekt(project_id)
    zadacha = await db.zadacha_sozdat(
        title=" ".join(text.split())[:60] or "Без названия",
        body=text,
        project_id=project_id,
        conversation_id=conv["id"],
        created_by=tg_id,
        chat_id=chat_id,
    )

    hod = await bot.send(chat_id, "⏳ Разбираю задачу…")
    zamysel = await engine.sprosit(
        ZAPROS_ZAMYSLA.format(proekt=proekt["name"], zadacha=text), model=MODEL_ZAMYSLA
    )
    if not zamysel:
        await bot.edit(
            chat_id, hod["message_id"],
            razmetka.soobshchit_oshibku(
                "Не удалось составить замысел — движок не ответил. "
                "Задача записана, её можно утвердить как есть через /tasks."),
        )
        return

    title, telo = _razobrat(zamysel, text)
    await db.zadacha_plan(zadacha["id"], telo)
    await db.execute("UPDATE tasks SET title = %s WHERE id = %s", (title, zadacha["id"]))

    await bot.delete(chat_id, hod["message_id"])
    await _pokazat(bot, chat_id, zadacha["id"], title, telo,
                   pometka=f"— {proekt['name']}")


async def reshenie(bot: Bot, chat_id: int, callback_id: str, data: str) -> None:
    """Нажатие кнопки под задачей: утвердить, уточнить, отклонить."""
    _, raw_id, deystvie = data.split(":", 2)
    task_id = int(raw_id)
    zadacha = await db.zadacha(task_id)

    if not zadacha:
        await bot.answer_callback(callback_id, "Задача не найдена")
        return

    if zadacha["status"] not in ("waiting",):
        await bot.answer_callback(
            callback_id, f"Задача уже {db.STATUSY.get(zadacha['status'], zadacha['status'])}"
        )
        return

    if deystvie == "no":
        await bot.answer_callback(callback_id, "Отклонено")
        await db.zadacha_status(task_id, "rejected")
        await _snyat_knopki(bot, zadacha, "❌ Отклонена")
        return

    if deystvie == "re":
        await bot.answer_callback(callback_id, "Жду уточнения")
        _zhdut_utochneniya[chat_id] = task_id
        await bot.send(
            chat_id,
            f"Что поправить в задаче {task_id}? Напишите следующим сообщением — "
            "перепишу замысел и спрошу снова. Чтобы передумать, нажмите /tasks.",
        )
        return

    # Утверждение
    await bot.answer_callback(callback_id, "Утверждено, работаю")
    await db.zadacha_status(task_id, "approved")
    await _snyat_knopki(bot, zadacha, "✅ Утверждена")
    await vypolnit(bot, chat_id, task_id)


async def utochnit(bot: Bot, chat_id: int, task_id: int, text: str) -> None:
    """Уточнение к задаче: дописать и переписать замысел."""
    zabyt_utochnenie(chat_id)
    zadacha = await db.zadacha(task_id)
    if not zadacha or zadacha["status"] != "waiting":
        await bot.send(chat_id, "Эта задача уже решена — поставьте новую через /task.")
        return

    telo = f"{zadacha['body']}\n\nУточнение: {text}"
    await db.execute("UPDATE tasks SET body = %s WHERE id = %s", (telo, task_id))

    hod = await bot.send(chat_id, "⏳ Переписываю замысел…")
    zamysel = await engine.sprosit(
        ZAPROS_ZAMYSLA.format(proekt=zadacha.get("project_name") or "—", zadacha=telo),
        model=MODEL_ZAMYSLA,
    )
    if not zamysel:
        await bot.edit(chat_id, hod["message_id"],
                       razmetka.soobshchit_oshibku("Движок не ответил, замысел прежний."))
        return

    title, plan = _razobrat(zamysel, telo)
    await db.zadacha_plan(task_id, plan)
    await db.execute("UPDATE tasks SET title = %s WHERE id = %s", (title, task_id))

    await bot.delete(chat_id, hod["message_id"])
    await _pokazat(bot, chat_id, task_id, title, plan, pometka="(с уточнением)")


async def vypolnit(bot: Bot, chat_id: int, task_id: int) -> None:
    """Выполнить утверждённую задачу в теме её проекта."""
    zadacha = await db.zadacha(task_id)
    if not zadacha:
        return
    conv = await db.dialog(zadacha["conversation_id"]) if zadacha["conversation_id"] else None
    if not conv:
        conv = await db.novyy_dialog(zadacha["title"], zadacha["project_id"])
        conv = await db.dialog(conv["id"])
        await db.execute("UPDATE tasks SET conversation_id = %s WHERE id = %s",
                         (conv["id"], task_id))

    note = f"\nУчесть дополнительно:\n{zadacha['note']}\n" if zadacha["note"] else ""
    prompt = ZAPROS_RABOTY.format(
        title=zadacha["title"], body=zadacha["body"],
        plan=zadacha["plan"] or "(замысел не составлялся)", note=note,
    )

    await db.zadacha_status(task_id, "running")
    itog = await engine.otvetit(bot, chat_id, conv, prompt)

    if itog:
        await db.zadacha_status(task_id, "done", result_text=itog.get("text") or "")
        await bot.send(chat_id, f"🏁 Задача {task_id} выполнена: {_bezopasno(zadacha['title'])}")
    else:
        await db.zadacha_status(task_id, "failed")
        await bot.send(
            chat_id,
            f"⚠️ Задача {task_id} не доведена до конца. Повторить — /tasks, "
            "кнопка «Повторить».",
        )


async def spisok(bot: Bot, chat_id: int) -> None:
    """Список задач: ожидающие и работающие сверху, под каждой — свои кнопки."""
    zadachi = await db.zadachi(limit=10)
    poyas = (await db.nastroyki()).get("timezone") or "Europe/Moscow"
    if not zadachi:
        await bot.send(
            chat_id,
            "Задач пока нет. Поставить — <code>/task что сделать</code>, "
            "или включите режим с утверждением: /mode.",
            html=True,
        )
        return

    for zadacha in zadachi:
        znachok = db.ZNACHKI.get(zadacha["status"], "•")
        stroka = (
            f"{znachok} <b>{zadacha['id']}. {_bezopasno(zadacha['title'])}</b>\n"
            f"{db.STATUSY.get(zadacha['status'], zadacha['status'])}"
            f" · {_bezopasno(zadacha.get('project_name') or 'без проекта')}"
            f" · {razmetka.kogda(zadacha['created_at'], poyas)}"
        )
        markup = None
        if zadacha["status"] == "waiting":
            markup = _klaviatura(zadacha["id"])
        elif zadacha["status"] in ("failed", "rejected"):
            markup = knopki([[("🔁 Повторить", f"t:{zadacha['id']}:again")]])
        await bot.send(chat_id, stroka, html=True, markup=markup)


async def povtorit(bot: Bot, chat_id: int, callback_id: str, task_id: int) -> None:
    """Вернуть отклонённую или сорвавшуюся задачу на утверждение."""
    zadacha = await db.zadacha(task_id)
    if not zadacha:
        await bot.answer_callback(callback_id, "Задача не найдена")
        return
    await bot.answer_callback(callback_id, "Возвращена на утверждение")
    await db.zadacha_status(task_id, "waiting")
    await _pokazat(bot, chat_id, task_id, zadacha["title"],
                   zadacha["plan"] or zadacha["body"], pometka="(повторно)")


async def _snyat_knopki(bot: Bot, zadacha: dict, podpis: str) -> None:
    """Убрать кнопки у решённой задачи: нажимать их второй раз нечего."""
    if not zadacha.get("message_id") or not zadacha.get("chat_id"):
        return
    await bot.edit_markup(zadacha["chat_id"], zadacha["message_id"], None)
    await bot.send(zadacha["chat_id"], f"{podpis}: задача {zadacha['id']}")


def _bezopasno(text: str) -> str:
    """Чужой текст внутрь HTML — только экранированным."""
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
