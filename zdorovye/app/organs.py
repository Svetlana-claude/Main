"""Фигурка человека: органы, их цвет по анализам и болезням, оценка Claude.

Цвет считается сразу, по правилам (`state_of`):
  0 — розовый: данные есть, всё в норме;
  1 — жёлтый: показатель вне нормы, текущая или хроническая болезнь;
  2 — тёмно-красный: показатель далеко за нормой (больше чем на половину
      ширины нормы, а при одной границе — в полтора раза) или так решил Claude;
  «?» — данных по органу нет или у Claude есть вопросы.
Вопросы и предположения пишет Claude по кнопке «Оценить» (`assess`), ответ
хранится в таблице assessments вместе с отпечатком данных: изменились данные —
оценка помечается устаревшей.
"""
import asyncio
import hashlib
import json
import os
import re
import shutil
import tempfile
from datetime import timedelta
from pathlib import Path

from fastapi import APIRouter, Form, Request

from . import config, db
from .labs import flag
from .web import age, member_for, parse_day, to, today

router = APIRouter()
_tasks: set[asyncio.Task] = set()

# Порядок важен: показатель относится к первому органу, чьё слово в нём нашлось
# («лейкоциты в моче» — почки, а не кровь).
ORGANS = [
    {"id": "kidneys", "name": "Почки и мочевой пузырь",
     "about": "Очищают кровь, держат водно-солевой баланс и давление.",
     "labs": ["моч", "креатинин", "мочевина", "скф", "клубочк", "цистатин", "альбумин/креатинин"],
     "ill": ["цистит", "пиелонеф", "почеч", "почк", "мочекамен", "уретрит", "нефр"],
     "usual": "креатинин и СКФ, мочевину, общий анализ мочи"},
    {"id": "thyroid", "name": "Щитовидная железа",
     "about": "Гормонами задаёт скорость обмена веществ, влияет на вес, настроение, сердце.",
     "labs": ["ттг", "тиреотроп", "т4", "т3", "тироксин", "трийодтиронин", "тпо", "тиреопероксид", "тиреоглобулин"],
     "ill": ["щитовид", "тиреоид", "гипотиреоз", "гипертиреоз", "зоб"],
     "usual": "ТТГ, при отклонении — свободный Т4 и антитела к ТПО"},
    {"id": "liver", "name": "Печень",
     "about": "Обезвреживает вещества, делает белки и желчь, хранит запасы энергии.",
     "labs": ["алт", "аланинаминотрансфераз", "аст", "аспартатаминотрансфераз", "билирубин", "ггт", "гамма-глутамил",
              "гаммаглутамил", "щелочная фосфатаза", "общий белок", "альбумин"],
     "ill": ["гепатит", "печен", "желчн", "холецист", "цирроз", "гепатоз"],
     "usual": "АЛТ, АСТ, билирубин, ГГТ"},
    {"id": "pancreas", "name": "Поджелудочная железа",
     "about": "Делает инсулин для сахара крови и ферменты для пищеварения.",
     "labs": ["глюкоз", "гликированн", "hba1c", "инсулин", "c-пептид", "с-пептид", "амилаз", "липаз", "homa"],
     "ill": ["диабет", "панкреат", "преддиабет", "инсулинорезист"],
     "usual": "глюкозу натощак, гликированный гемоглобин"},
    {"id": "heart", "name": "Сердце и сосуды",
     "about": "Качает кровь по телу. Холестерин и давление говорят о сосудах.",
     "labs": ["холестерин", "лпнп", "лпвп", "лпонп", "триглицерид", "атероген", "тропонин", "probnp", "гомоцистеин",
              "липопротеин"],
     "ill": ["гипертон", "давлен", "аритм", "тахикард", "брадикард", "ишеми", "стенокард", "инфаркт", "варикоз",
             "тромбоз", "сердеч"],
     "usual": "холестерин с фракциями (липидограмму), давление"},
    {"id": "stomach", "name": "Желудок",
     "about": "Переваривает пищу кислотой и ферментами.",
     "labs": ["хеликобакт", "helicobacter", "пепсиноген", "гастрин"],
     "ill": ["гастрит", "язв", "изжог", "рефлюкс", "желуд", "гэрб", "диспепс"],
     "usual": "при жалобах — анализ на хеликобактер, гастроскопию"},
    {"id": "intestines", "name": "Кишечник",
     "about": "Всасывает питательные вещества и воду, в нём живут полезные бактерии.",
     "labs": ["кальпротектин", "скрытая кровь", "копрограм", "кал "],
     "ill": ["колит", "кишеч", "диаре", "запор", "ротавирус", "норовирус", "отравлен", "дисбактер", "геморро",
             "синдром раздражённого", "сибр"],
     "usual": "после 45–50 лет — анализ кала на скрытую кровь или колоноскопию"},
    {"id": "lungs", "name": "Лёгкие и дыхание",
     "about": "Дают крови кислород и забирают углекислый газ.",
     "labs": ["сатурац", "spo2"],
     "ill": ["бронхит", "пневмон", "астм", "кашел", "трахеит", "ларингит", "орви", "грипп", "covid", "ковид",
             "простуд", "ангин", "фарингит", "тонзиллит", "синусит", "гайморит", "ринит"],
     "usual": "флюорографию раз в год-два"},
    {"id": "brain", "name": "Мозг и нервная система",
     "about": "Управляет всем телом, памятью, сном и настроением.",
     "labs": [],
     "ill": ["мигрен", "головн", "инсульт", "сотрясен", "невр", "невралг", "депресс", "тревожн", "бессонн",
             "эпилеп"],
     "usual": "при жалобах — осмотр невролога"},
    {"id": "eyes", "name": "Глаза",
     "about": "Зрение. Раз в год стоит проверять остроту и давление в глазу.",
     "labs": ["внутриглазн"],
     "ill": ["близорук", "дальнозор", "конъюнктив", "глауком", "катаракт", "зрени", "астигмат", "ячмень"],
     "usual": "осмотр окулиста раз в год"},
    {"id": "bones", "name": "Кости, суставы, позвоночник",
     "about": "Опора и движение. Для крепких костей нужны кальций и витамин D.",
     "labs": ["витамин d", "25-oh", "25(oh)", "кальций", "фосфор", "паратгормон", "мочевая кислота"],
     "ill": ["остеохондр", "артрит", "артроз", "перелом", "сколиоз", "грыж", "остеопор", "подагр", "радикулит",
             "ушиб", "растяжен", "сустав", "спин"],
     "usual": "витамин D, кальций"},
    {"id": "blood", "name": "Кровь",
     "about": "Переносит кислород, борется с инфекциями, останавливает кровотечения.",
     "labs": ["гемоглобин", "эритроцит", "лейкоцит", "тромбоцит", "гематокрит", "соэ", "ферритин", "желез",
              "трансферрин", "b12", "в12", "фолиев", "mcv", "mch", "rdw", "нейтрофил", "лимфоцит", "моноцит",
              "эозинофил", "базофил", "с-реактивн", "c-реактивн", "срб"],
     "ill": ["анеми", "малокров"],
     "usual": "общий анализ крови раз в год, ферритин"},
]
BY_ID = {o["id"]: o for o in ORGANS}


def organ_of_lab(key: str) -> str | None:
    for o in ORGANS:
        if any(word in key for word in o["labs"]):
            return o["id"]
    return None


def organs_of_text(text: str) -> set[str]:
    text = db.key_of(text)
    return {o["id"] for o in ORGANS if any(word in text for word in o["ill"])}


def severity(r: dict) -> int:
    """0 — в норме, 1 — вне нормы, 2 — далеко за нормой."""
    value, low, high = r.get("value"), r.get("low"), r.get("high")
    if not flag(value, low, high):
        return 0
    if low is not None and high is not None and high > low:
        beyond = (low - value) if value < low else (value - high)
        return 2 if beyond > 0.5 * (high - low) else 1
    if high is not None and value > high:
        return 2 if value > high * 1.5 else 1
    if low is not None and value < low:
        return 2 if value < low * 0.5 else 1
    return 1


def _line(level: int, labs: list[dict], ill: list[dict], chronic: bool) -> str:
    out = [r for r in labs if r["sev"]]
    if out:
        r = max(out, key=lambda r: r["sev"])
        rest = f" и ещё {len(out) - 1}" if len(out) > 1 else ""
        return f"Вне нормы: {r['name']}{rest}"
    if ill:
        return f"{'Болеет' if not ill[0]['ended'] else 'Недавно'}: {ill[0]['title']}"
    if chronic:
        return "Есть хроническое — смотри «Основное»"
    if labs:
        return f"В норме по {len(labs)} показ."
    return "Данных пока нет"


def state_of(member: dict, latest: list[dict], illnesses: list[dict], assessment: dict | None) -> list[dict]:
    """Состояние каждого органа для фигурки и блоков."""
    recent = today() - timedelta(days=14)
    chronic = organs_of_text(" ".join([member.get("chronic", ""), member.get("allergies", "")]))
    found = assessment["organs"] if assessment else {}
    out = []
    for o in ORGANS:
        labs = [{**r, "sev": severity(r)} for r in latest if organ_of_lab(r["key"]) == o["id"]]
        ill_all = [i for i in illnesses if o["id"] in organs_of_text(f"{i['title']} {i['notes']}")]
        ill_now = [i for i in ill_all if not i["ended"] or (parse_day(i["ended"]) or recent) >= recent]
        level = max([r["sev"] for r in labs] + [1 if ill_now or o["id"] in chronic else 0])
        a = found.get(o["id"]) or {}
        if isinstance(a.get("level"), int) and a["level"] in (0, 1, 2) and labs + ill_all:
            level = max(level, a["level"])
        has_data = bool(labs or ill_all or o["id"] in chronic)
        out.append({**o, "level": level, "has_data": has_data,
                    "ask": not has_data or bool(a.get("questions")),
                    "line": a.get("summary") or _line(level, labs, ill_now, o["id"] in chronic),
                    "labs": sorted(labs, key=lambda r: (-r["sev"], r["name"].lower())),
                    "ill": ill_all[:8], "questions": a.get("questions") or [],
                    "suggestions": a.get("suggestions") or []})
    return out


# ── Оценка Claude ────────────────────────────────────────────────────────

PROMPT = """Ты помогаешь семье следить за здоровьем. Ниже — данные одного человека
(JSON): возраст, пол, хронические болезни, аллергии, лекарства, витамины,
дневник болезней, прививки и все анализы с нормами по датам.

Оцени по органам: {organs}.
Ответь ТОЛЬКО объектом JSON без пояснений и без ``` вокруг:
{{"general": "2–3 фразы об общем состоянии",
  "organs": {{"liver": {{"level": 0, "summary": "одна короткая строка",
               "questions": ["чего не хватает, чтобы оценить"],
               "suggestions": ["что стоит сделать: какой анализ сдать, к какому врачу, когда"]}}}}}}

Правила:
- level: 0 — всё в порядке, 1 — есть отклонения, стоит обратить внимание,
  2 — нужно к врачу в ближайшие дни; null — данных нет совсем;
- пиши по-русски, просто, без страшилок и без диагнозов — только «может
  говорить о…», «стоит проверить…»; учитывай возраст, пол и динамику по датам;
- questions — конкретно, чего не хватает (какого анализа, какой жалобы); если
  данных нет — что обычно проверяют в этом возрасте;
- suggestions — не больше трёх, конкретные; если есть признаки срочности —
  первым пунктом «к врачу в ближайшие дни» и почему;
- верни все органы из списка.

Данные:
{data}"""


def snapshot(member_id: int) -> dict:
    m = db.one("SELECT * FROM members WHERE id = ?", (member_id,))
    since = (today() - timedelta(days=3 * 365)).isoformat()
    return {
        "возраст": age(m["birth_date"]), "пол": {"ж": "женский", "м": "мужской"}.get(m["sex"], "не указан"),
        "хронические": m["chronic"], "аллергии": m["allergies"], "лекарства": m["medicines"],
        "витамины": m["vitamins"], "заметки": m["notes"],
        "болезни": [{k: i[k] for k in ("started", "ended", "title", "treatment", "notes")}
                    for i in db.rows("SELECT * FROM illnesses WHERE member_id = ? AND started >= ? ORDER BY started",
                                     (member_id, since))],
        "прививки": [{k: v[k] for k in ("name", "done_on", "next_due")}
                     for v in db.rows("SELECT * FROM vaccines WHERE member_id = ?", (member_id,))],
        "анализы": [{k: r[k] for k in ("taken_on", "name", "value", "value_text", "unit", "low", "high", "ref_text")}
                    for r in db.rows("SELECT * FROM results WHERE member_id = ? ORDER BY taken_on, id", (member_id,))],
    }


def fingerprint(member_id: int) -> str:
    return hashlib.sha256(json.dumps(snapshot(member_id), ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def argv() -> list[str]:
    return [config.CLAUDE_BIN, "-p", "--output-format", "json", "--model", config.PARSE_MODEL,
            "--no-session-persistence", "--permission-mode", "default",
            "--disallowed-tools", "Bash", "Read", "Edit", "Write", "Glob", "Grep", "NotebookEdit",
            "WebFetch", "WebSearch", "Task"]


def read_answer(text: str) -> dict:
    match = re.search(r"\{.*\}", text or "", re.S)
    if not match:
        raise ValueError("в ответе нет оценки")
    raw = json.loads(match.group(0))
    organs = {}
    for oid, a in (raw.get("organs") or {}).items():
        if oid not in BY_ID or not isinstance(a, dict):
            continue
        level = a.get("level")
        organs[oid] = {
            "level": level if level in (0, 1, 2) else None,
            "summary": str(a.get("summary") or "").strip()[:160],
            "questions": [str(q).strip()[:300] for q in (a.get("questions") or []) if str(q).strip()][:4],
            "suggestions": [str(s).strip()[:300] for s in (a.get("suggestions") or []) if str(s).strip()][:3],
        }
    return {"general": str(raw.get("general") or "").strip()[:600], "organs": organs}


async def run_assessment(member_id: int) -> None:
    data = snapshot(member_id)
    prompt = PROMPT.format(organs=", ".join(f"{o['id']} ({o['name']})" for o in ORGANS),
                           data=json.dumps(data, ensure_ascii=False, indent=1))
    work = Path(tempfile.mkdtemp(prefix="zd-ocenka-"))
    try:
        env = {k: v for k, v in os.environ.items() if not k.startswith("ZD_")}
        proc = await asyncio.create_subprocess_exec(*argv(), stdin=asyncio.subprocess.PIPE,
                                                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                                                    cwd=str(work), env=env)
        out, err = await asyncio.wait_for(proc.communicate(prompt.encode()), timeout=config.PARSE_TIMEOUT_SEC)
        reply = json.loads(out)
        if reply.get("is_error"):
            raise ValueError(str(reply.get("result"))[:300])
        result = read_answer(str(reply.get("result") or ""))
        db.run("UPDATE assessments SET state = 'ready', data = ?, error = '', print = ? WHERE member_id = ?",
               (json.dumps(result, ensure_ascii=False), fingerprint(member_id), member_id))
    except Exception as exc:                                   # noqa: BLE001
        text = "Claude не успел за 10 минут" if isinstance(exc, asyncio.TimeoutError) else str(exc)
        db.run("UPDATE assessments SET state = 'error', error = ? WHERE member_id = ?", (text[:300], member_id))
    finally:
        shutil.rmtree(work, ignore_errors=True)


def assessment_of(member_id: int) -> dict | None:
    row = db.one("SELECT * FROM assessments WHERE member_id = ?", (member_id,))
    if not row:
        return None
    data = json.loads(row["data"]) if row["data"] else {"general": "", "organs": {}}
    return {**row, **data, "stale": row["state"] == "ready" and row["print"] != fingerprint(member_id)}


@router.post("/m/{member_id}/assess", name="assess")
async def assess(request: Request, member_id: int, csrf: str = Form("")):
    member_for(request, member_id, edit=True, csrf=csrf)
    row = db.one("SELECT state FROM assessments WHERE member_id = ?", (member_id,))
    if not row or row["state"] != "running":
        db.run("INSERT INTO assessments (member_id, state, created_at) VALUES (?, 'running', ?) "
               "ON CONFLICT(member_id) DO UPDATE SET state = 'running', error = '', created_at = excluded.created_at",
               (member_id, db.now()))
        task = asyncio.get_running_loop().create_task(run_assessment(member_id))
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)
    return to(request, "member", member_id=member_id)
