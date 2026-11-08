"""Анализы: загрузка бланка, разбор Claude, проверка Светланой, графики."""
import asyncio
import io
import json
import os
import re
import secrets
import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from markupsafe import Markup, escape
from PIL import Image, ImageOps

from . import config, db
from .web import can_edit, day, member_for, num, page, parse_day, to, today

router = APIRouter()

_one_at_a_time = asyncio.Semaphore(1)       # разбор тяжёлый — по одному
_tasks: set[asyncio.Task] = set()           # чтобы фоновые разборы не собрал сборщик мусора

PROMPT = """В этой папке лежит файл {name} — бланк медицинского анализа (фото или PDF).
Прочитай его и выпиши ВСЕ показатели. Ответь ТОЛЬКО объектом JSON, без пояснений
и без ``` вокруг, строго в таком виде:

{{"date": "ГГГГ-ММ-ДД или пусто, если даты сдачи нет",
  "lab": "название лаборатории или клиники, или пусто",
  "items": [
    {{"name": "Гемоглобин", "value": 135, "value_text": "", "unit": "г/л",
      "low": 120, "high": 140, "ref_text": "120–140"}}
  ]}}

Правила:
- name — общепринятое русское название показателя, без сокращений, если они
  расшифровываются однозначно (HGB → Гемоглобин), как на бланке иначе;
- value — число (точка как разделитель); если результат не число
  («отрицательно», «не обнаружено», «1+»), value = null, а текст — в value_text;
- low/high — границы нормы числами, если они есть; если норма одна граница
  («< 5»), вторую оставь null; ref_text — норма как написано на бланке;
- ничего не придумывай: чего нет на бланке — пусто или null;
- если файл не похож на анализ, верни {{"date": "", "lab": "", "items": []}}."""


# ── Числа ────────────────────────────────────────────────────────────────

def to_number(value) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", ".").replace(" ", "").replace(" ", "")
    try:
        return float(text)
    except ValueError:
        return None


def flag(value: float | None, low: float | None, high: float | None) -> str:
    if value is None:
        return ""
    if low is not None and value < low:
        return "ниже"
    if high is not None and value > high:
        return "выше"
    return ""


# ── Файлы ────────────────────────────────────────────────────────────────

def _kind(data: bytes) -> str | None:
    if data[:3] == b"\xff\xd8\xff" or data[:8] == b"\x89PNG\r\n\x1a\n" or data[:4] == b"RIFF":
        return "image"
    if data[4:12] in (b"ftypheic", b"ftypheix", b"ftypmif1", b"ftypmsf1", b"ftyphevc"):
        return "image"
    if data[:5] == b"%PDF-":
        return "pdf"
    return None


def store(data: bytes) -> tuple[str, str]:
    """Сохранить бланк: фото — ужатым JPEG (с поворотом по EXIF), PDF — как есть.
    Возвращает (имя файла, тип)."""
    kind = _kind(data)
    if kind is None:
        raise HTTPException(400, "Нужен снимок (JPEG, PNG, HEIC) или PDF")
    name = secrets.token_hex(16)
    if kind == "pdf":
        path = config.FILES_DIR / f"{name}.pdf"
        path.write_bytes(data)
        path.chmod(0o600)
        return path.name, "application/pdf"
    if data[4:8] == b"ftyp":
        import pillow_heif
        pillow_heif.register_heif_opener()
    try:
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img).convert("RGB")
    except Exception as exc:                                   # noqa: BLE001
        raise HTTPException(400, "Снимок не открылся — попробуй другой файл") from exc
    img.thumbnail((config.IMAGE_MAX_SIDE, config.IMAGE_MAX_SIDE))
    path = config.FILES_DIR / f"{name}.jpg"
    img.save(path, "JPEG", quality=85, optimize=True)
    path.chmod(0o600)
    return path.name, "image/jpeg"


# ── Разбор Claude ────────────────────────────────────────────────────────

def parse_argv() -> list[str]:
    return [config.CLAUDE_BIN, "-p", "--output-format", "json", "--model", config.PARSE_MODEL,
            "--no-session-persistence", "--permission-mode", "default",
            "--allowed-tools", "Read",
            "--disallowed-tools", "Bash", "Edit", "Write", "NotebookEdit", "WebFetch", "WebSearch", "Task"]


def read_answer(text: str) -> dict:
    """Ответ Claude → {"date", "lab", "items"} с проверкой типов."""
    match = re.search(r"\{.*\}", text or "", re.S)
    if not match:
        raise ValueError("в ответе нет таблицы показателей")
    raw = json.loads(match.group(0))
    items = []
    for it in raw.get("items") or []:
        if not isinstance(it, dict) or not str(it.get("name") or "").strip():
            continue
        value = to_number(it.get("value"))
        items.append({
            "name": str(it["name"]).strip()[:120],
            "value": value,
            "value_text": "" if value is not None else str(it.get("value_text") or it.get("value") or "").strip()[:60],
            "unit": str(it.get("unit") or "").strip()[:30],
            "low": to_number(it.get("low")),
            "high": to_number(it.get("high")),
            "ref_text": str(it.get("ref_text") or "").strip()[:80],
        })
    d = parse_day(str(raw.get("date") or ""))
    return {"date": d.isoformat() if d else "", "lab": str(raw.get("lab") or "").strip()[:120], "items": items}


async def run_claude(path: Path) -> dict:
    """Claude читает копию бланка в пустой временной папке и только читает."""
    work = Path(tempfile.mkdtemp(prefix="zd-razbor-"))
    try:
        target = work / f"blank{path.suffix}"
        shutil.copyfile(path, target)
        env = {k: v for k, v in os.environ.items() if not k.startswith("ZD_")}
        proc = await asyncio.create_subprocess_exec(
            *parse_argv(), stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, cwd=str(work), env=env)
        try:
            out, err = await asyncio.wait_for(proc.communicate(PROMPT.format(name=target.name).encode()),
                                              timeout=config.PARSE_TIMEOUT_SEC)
        except asyncio.TimeoutError:
            proc.kill()
            raise ValueError("Claude не успел разобрать бланк за 10 минут")
        try:
            data = json.loads(out)
        except ValueError:
            tail = err.decode("utf-8", "replace").strip().splitlines()[-1:] or ["нет ответа"]
            raise ValueError(f"Claude не ответил: {tail[0][:200]}")
        if data.get("is_error"):
            raise ValueError(str(data.get("result") or "ошибка Claude")[:300])
        return read_answer(str(data.get("result") or ""))
    finally:
        shutil.rmtree(work, ignore_errors=True)


async def parse_doc(doc_id: int) -> None:
    doc = db.one("SELECT * FROM docs WHERE id = ?", (doc_id,))
    if not doc:
        return
    async with _one_at_a_time:
        try:
            result = await run_claude(config.FILES_DIR / doc["file"])
        except Exception as exc:                               # noqa: BLE001
            db.run("UPDATE docs SET state = 'error', error = ? WHERE id = ?", (str(exc)[:400], doc_id))
            return
    if not result["items"]:
        db.run("UPDATE docs SET state = 'error', error = ? WHERE id = ?",
               ("Показателей на бланке не нашлось. Можно ввести вручную или загрузить снимок почётче.", doc_id))
        return
    db.run("UPDATE docs SET state = 'review', draft = ?, error = '', "
           "taken_on = CASE WHEN taken_on = '' THEN ? ELSE taken_on END, "
           "lab = CASE WHEN lab = '' THEN ? ELSE lab END WHERE id = ?",
           (json.dumps(result["items"], ensure_ascii=False), result["date"], result["lab"], doc_id))


def start_parse(doc_id: int) -> None:
    db.run("UPDATE docs SET state = 'parsing', error = '' WHERE id = ?", (doc_id,))
    task = asyncio.get_running_loop().create_task(parse_doc(doc_id))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


# ── Выборки ──────────────────────────────────────────────────────────────

def docs_of(member_id: int) -> list[dict]:
    return db.rows("SELECT d.*, (SELECT count(*) FROM results r WHERE r.doc_id = d.id) AS n "
                   "FROM docs d WHERE member_id = ? ORDER BY taken_on DESC, id DESC", (member_id,))


def latest(member_id: int) -> list[dict]:
    """Последнее значение каждого показателя, с отметкой вне нормы."""
    rows = db.rows("SELECT * FROM results WHERE member_id = ? ORDER BY taken_on, id", (member_id,))
    last: dict[str, dict] = {}
    counts: dict[str, int] = {}
    for r in rows:
        last[r["key"]] = r
        counts[r["key"]] = counts.get(r["key"], 0) + 1
    out = []
    for key, r in last.items():
        out.append({**r, "flag": flag(r["value"], r["low"], r["high"]), "count": counts[key]})
    return sorted(out, key=lambda r: (r["flag"] == "", r["name"].lower()))


# ── Страницы ─────────────────────────────────────────────────────────────

@router.post("/m/{member_id}/docs", name="doc_upload")
async def doc_upload(request: Request, member_id: int, blank: UploadFile = File(...),
                     csrf: str = Form("")):
    member_for(request, member_id, edit=True, csrf=csrf)
    data = await blank.read(config.MAX_UPLOAD_MB * 1024 * 1024 + 1)
    if len(data) > config.MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"Файл больше {config.MAX_UPLOAD_MB} МБ")
    if not data:
        raise HTTPException(400, "Файл пустой")
    name, mime = store(data)
    doc_id = db.insert("INSERT INTO docs (member_id, file, orig_name, mime, state, created_at) "
                       "VALUES (?, ?, ?, ?, 'parsing', ?)",
                       (member_id, name, (blank.filename or "")[:120], mime, db.now()))
    start_parse(doc_id)
    return to(request, "doc", member_id=member_id, doc_id=doc_id)


def _doc_for(request: Request, member_id: int, doc_id: int, edit: bool = False, csrf: str | None = None):
    sess, member = member_for(request, member_id, edit=edit, csrf=csrf)
    doc = db.one("SELECT * FROM docs WHERE id = ? AND member_id = ?", (doc_id, member_id))
    if not doc:
        raise HTTPException(404, "Такого бланка нет")
    return sess, member, doc


@router.get("/m/{member_id}/docs/{doc_id}", name="doc")
def doc_page(request: Request, member_id: int, doc_id: int):
    sess, member, doc = _doc_for(request, member_id, doc_id)
    if doc["state"] == "ready":
        items = db.rows("SELECT * FROM results WHERE doc_id = ? ORDER BY id", (doc_id,))
    elif doc["draft"]:
        items = json.loads(doc["draft"])
    else:
        items = []
    for it in items:
        it["flag"] = flag(it.get("value"), it.get("low"), it.get("high"))
    return page(request, "doc.html", {"sess": sess, "active": "home", "m": member, "doc": doc,
                                      "items": items, "edit": can_edit(sess, member_id),
                                      "blank_rows": 3 if items else 8})


@router.post("/m/{member_id}/docs/{doc_id}/save", name="doc_save")
async def doc_save(request: Request, member_id: int, doc_id: int):
    form = await request.form()
    _doc_for(request, member_id, doc_id, edit=True, csrf=str(form.get("csrf", "")))
    taken = parse_day(str(form.get("taken_on", "")))
    if not taken:
        raise HTTPException(400, "Укажи дату сдачи анализа")
    names, values = form.getlist("name"), form.getlist("value")
    units, lows, highs, refs = form.getlist("unit"), form.getlist("low"), form.getlist("high"), form.getlist("ref_text")
    rows = []
    for i, raw_name in enumerate(names):
        name = str(raw_name).strip()[:120]
        raw_value = str(values[i] if i < len(values) else "").strip()[:60]
        if not name or not raw_value:
            continue
        value = to_number(raw_value)
        rows.append((doc_id, member_id, taken.isoformat(), name, db.key_of(name), value,
                     "" if value is not None else raw_value,
                     str(units[i] if i < len(units) else "").strip()[:30],
                     to_number(lows[i] if i < len(lows) else None),
                     to_number(highs[i] if i < len(highs) else None),
                     str(refs[i] if i < len(refs) else "").strip()[:80]))
    if not rows:
        raise HTTPException(400, "Нет ни одного показателя со значением")
    with db.tx() as con:
        con.execute("DELETE FROM results WHERE doc_id = ?", (doc_id,))
        con.executemany("INSERT INTO results (doc_id, member_id, taken_on, name, key, value, value_text, "
                        "unit, low, high, ref_text) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
        con.execute("UPDATE docs SET state = 'ready', taken_on = ?, lab = ?, draft = '', error = '' WHERE id = ?",
                    (taken.isoformat(), str(form.get("lab", "")).strip()[:120], doc_id))
    return to(request, "member", member_id=member_id)


@router.post("/m/{member_id}/docs/{doc_id}/parse", name="doc_parse")
async def doc_reparse(request: Request, member_id: int, doc_id: int, csrf: str = Form("")):
    _, _, doc = _doc_for(request, member_id, doc_id, edit=True, csrf=csrf)
    if doc["state"] != "parsing":
        start_parse(doc_id)
    return to(request, "doc", member_id=member_id, doc_id=doc_id)


@router.post("/m/{member_id}/docs/{doc_id}/delete", name="doc_delete")
def doc_delete(request: Request, member_id: int, doc_id: int, csrf: str = Form("")):
    _, _, doc = _doc_for(request, member_id, doc_id, edit=True, csrf=csrf)
    db.run("DELETE FROM docs WHERE id = ?", (doc_id,))
    (config.FILES_DIR / doc["file"]).unlink(missing_ok=True)
    return to(request, "member", member_id=member_id)


@router.get("/m/{member_id}/docs/{doc_id}/file", name="doc_file")
def doc_file(request: Request, member_id: int, doc_id: int):
    _, _, doc = _doc_for(request, member_id, doc_id)
    path = config.FILES_DIR / doc["file"]
    if not path.is_file():
        raise HTTPException(404, "Файл не найден")
    return FileResponse(path, media_type=doc["mime"], headers={
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
        "Content-Disposition": "inline"})


@router.get("/m/{member_id}/chart", name="chart")
def chart_page(request: Request, member_id: int, key: str):
    sess, member = member_for(request, member_id)
    rows = db.rows("SELECT * FROM results WHERE member_id = ? AND key = ? ORDER BY taken_on, id",
                   (member_id, key))
    if not rows:
        raise HTTPException(404, "Такого показателя нет")
    for r in rows:
        r["flag"] = flag(r["value"], r["low"], r["high"])
    return page(request, "chart.html", {"sess": sess, "active": "home", "m": member, "rows": rows,
                                        "title": rows[-1]["name"], "svg": chart_svg(rows)})


def chart_svg(rows: list[dict]) -> Markup:
    """График показателя по датам: линия, точки, полоса нормы (по последнему бланку)."""
    pts = [(parse_day(r["taken_on"]), r["value"], r["flag"]) for r in rows if r["value"] is not None]
    pts = [p for p in pts if p[0]]
    if not pts:
        return Markup('<p class="muted">Значения не числовые — график не строится.</p>')
    w, h, left, right, top, bottom = 640, 260, 52, 20, 16, 40
    last = rows[-1]
    low, high = last["low"], last["high"]
    values = [v for _, v, _ in pts] + [x for x in (low, high) if x is not None]
    vmin, vmax = min(values), max(values)
    pad = (vmax - vmin) * 0.12 or abs(vmax) * 0.1 or 1
    vmin, vmax = vmin - pad, vmax + pad
    d0, d1 = pts[0][0], pts[-1][0]
    span = (d1 - d0).days

    def x(d):
        return left + ((d - d0).days / span if span else 0.5) * (w - left - right)

    def y(v):
        return top + (1 - (v - vmin) / (vmax - vmin)) * (h - top - bottom)

    parts = [f'<svg class="chart" viewBox="0 0 {w} {h}" role="img" aria-label="График по датам">']
    if low is not None or high is not None:
        y_top = y(high) if high is not None else top
        y_bot = y(low) if low is not None else h - bottom
        parts.append(f'<rect class="norm" x="{left}" y="{y_top:.1f}" width="{w - left - right}" '
                     f'height="{max(y_bot - y_top, 1):.1f}"><title>Норма</title></rect>')
    # Подписи слева: границы нормы и крайние значения, без наложений
    ticks, placed = sorted({round(v, 2) for v in values}, reverse=True), []
    for v in ticks:
        if all(abs(y(v) - p) >= 14 for p in placed):
            placed.append(y(v))
            parts.append(f'<text class="axis" x="{left - 6}" y="{y(v) + 4:.1f}" text-anchor="end">{escape(num(v))}</text>')
    parts.append(f'<line class="base" x1="{left}" y1="{h - bottom}" x2="{w - right}" y2="{h - bottom}"/>')
    if len(pts) > 1:
        line = " ".join(f"{x(d):.1f},{y(v):.1f}" for d, v, _ in pts)
        parts.append(f'<polyline class="line" points="{line}"/>')
    every = max(1, len(pts) // 6)
    for i, (d, v, fl) in enumerate(pts):
        cls = "pt out" if fl else "pt"
        parts.append(f'<circle class="{cls}" cx="{x(d):.1f}" cy="{y(v):.1f}" r="5">'
                     f'<title>{escape(day(d.isoformat()))}: {escape(num(v))}</title></circle>')
        if i % every == 0 or i == len(pts) - 1:
            parts.append(f'<text class="axis" x="{x(d):.1f}" y="{h - bottom + 18}" text-anchor="middle">'
                         f'{escape(f"{d:%d.%m.%y}")}</text>')
    parts.append("</svg>")
    return Markup("".join(parts))


def today_iso() -> str:
    return today().isoformat()
