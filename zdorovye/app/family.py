"""Главная, странички членов семьи: основное, дневник болезней, прививки."""
from collections import defaultdict
from datetime import timedelta

from fastapi import APIRouter, Form, HTTPException, Request

from . import config, db, labs, organs
from .auth import asked_count
from .web import can_edit, member_for, need, need_owner, owner, page, parse_day, to, today, visible_members

router = APIRouter()

PROFILE_FIELDS = ("name", "birth_date", "sex", "blood", "chronic", "allergies", "medicines", "vitamins", "notes")


def _clean_day(value: str) -> str:
    d = parse_day(value)
    return d.isoformat() if d else ""


def vaccine_state(next_due: str) -> str:
    """'' | soon (в ближайший месяц) | late (просрочена)."""
    d = parse_day(next_due)
    if not d:
        return ""
    if d < today():
        return "late"
    if d <= today() + timedelta(days=config.SOON_DAYS):
        return "soon"
    return ""


def _flags(member_id: int) -> dict:
    """Что показать на карточке: показатели вне нормы в последних анализах, прививки."""
    out = [r for r in labs.latest(member_id) if r["flag"]]
    vac = [v for v in db.rows("SELECT name, next_due FROM vaccines WHERE member_id = ?", (member_id,))
           if vaccine_state(v["next_due"])]
    return {"out": out, "vac": vac}


@router.get("/", name="home")
def home(request: Request):
    sess = need(request)
    if not owner(sess):
        mine = db.one("SELECT * FROM members WHERE id = ?", (sess["member_id"],))
        others = db.rows("SELECT id, name FROM members WHERE id != ? ORDER BY name", (sess["member_id"],))
        states = {r["member_id"]: r["state"] for r in db.rows(
            "SELECT member_id, state FROM access WHERE user_id = ? ORDER BY id", (sess["user_id"],))}
        return page(request, "home_member.html", {"sess": sess, "active": "home", "mine": mine,
                                                  "others": others, "states": states})
    members = visible_members(sess)
    cards = [{**m, **_flags(m["id"])} for m in members]
    return page(request, "home.html", {"sess": sess, "active": "home", "cards": cards,
                                       "asked": asked_count()})


@router.post("/members/new", name="member_new")
def member_new(request: Request, name: str = Form(""), birth_date: str = Form(""),
               sex: str = Form(""), csrf: str = Form("")):
    need_owner(request, csrf)
    name = name.strip()[:80]
    if not name:
        raise HTTPException(400, "Нужно имя")
    member_id = db.insert("INSERT INTO members (name, birth_date, sex, created_at) VALUES (?, ?, ?, ?)",
                          (name, _clean_day(birth_date), sex if sex in ("ж", "м") else "", db.now()))
    return to(request, "member", member_id=member_id)


@router.get("/m/{member_id}", name="member")
def member_page(request: Request, member_id: int):
    sess, member = member_for(request, member_id)
    ill = db.rows("SELECT * FROM illnesses WHERE member_id = ? ORDER BY started DESC, id DESC", (member_id,))
    vac = db.rows("SELECT * FROM vaccines WHERE member_id = ? ORDER BY done_on DESC, id DESC", (member_id,))
    for v in vac:
        v["state"] = vaccine_state(v["next_due"])
    latest = labs.latest(member_id)
    assessment = organs.assessment_of(member_id)
    return page(request, "member.html", {
        "sess": sess, "active": "home", "m": member, "edit": can_edit(sess, member_id),
        "ill": ill, "ill_stats": illness_stats(ill), "vac": vac,
        "latest": latest, "docs": labs.docs_of(member_id),
        "body": {o["id"]: o for o in organs.state_of(member, latest, ill, assessment)},
        "assessment": assessment, "today": today().isoformat()})


@router.post("/m/{member_id}/profile", name="member_profile")
async def member_profile(request: Request, member_id: int):
    form = await request.form()
    member_for(request, member_id, edit=True, csrf=str(form.get("csrf", "")))
    values = {f: str(form.get(f, "")).strip()[:4000] for f in PROFILE_FIELDS}
    if not values["name"]:
        raise HTTPException(400, "Нужно имя")
    values["birth_date"] = _clean_day(values["birth_date"])
    if values["sex"] not in ("ж", "м"):
        values["sex"] = ""
    db.run(f"UPDATE members SET {', '.join(f'{f} = ?' for f in PROFILE_FIELDS)} WHERE id = ?",
           (*values.values(), member_id))
    return to(request, "member", member_id=member_id)


@router.post("/m/{member_id}/delete", name="member_delete")
def member_delete(request: Request, member_id: int, sure: str = Form(""), csrf: str = Form("")):
    need_owner(request, csrf)
    if sure != "да":
        raise HTTPException(400, "Поставь галочку «Да, удалить насовсем»")
    files = [r["file"] for r in db.rows("SELECT file FROM docs WHERE member_id = ?", (member_id,))]
    db.run("DELETE FROM members WHERE id = ?", (member_id,))
    for name in files:
        (config.FILES_DIR / name).unlink(missing_ok=True)
    return to(request, "home")


# ── Болезни ──────────────────────────────────────────────────────────────

def illness_stats(ill: list[dict]) -> list[dict]:
    """По годам: сколько раз болел и сколько дней всего (где известен конец)."""
    years: dict[int, dict] = defaultdict(lambda: {"count": 0, "days": 0})
    for row in ill:
        start, end = parse_day(row["started"]), parse_day(row["ended"])
        if not start:
            continue
        years[start.year]["count"] += 1
        if end and end >= start:
            years[start.year]["days"] += (end - start).days + 1
    return [{"year": y, **v} for y, v in sorted(years.items(), reverse=True)]


@router.post("/m/{member_id}/ill", name="ill_add")
def ill_add(request: Request, member_id: int, started: str = Form(""), ended: str = Form(""),
            title: str = Form(""), treatment: str = Form(""), notes: str = Form(""), csrf: str = Form("")):
    member_for(request, member_id, edit=True, csrf=csrf)
    if not title.strip() or not _clean_day(started):
        raise HTTPException(400, "Нужны дата начала и что было")
    db.insert("INSERT INTO illnesses (member_id, started, ended, title, treatment, notes, created_at) "
              "VALUES (?, ?, ?, ?, ?, ?, ?)",
              (member_id, _clean_day(started), _clean_day(ended), title.strip()[:200],
               treatment.strip()[:2000], notes.strip()[:2000], db.now()))
    return to(request, "member", member_id=member_id)


@router.post("/m/{member_id}/ill/{row_id}/delete", name="ill_delete")
def ill_delete(request: Request, member_id: int, row_id: int, csrf: str = Form("")):
    member_for(request, member_id, edit=True, csrf=csrf)
    db.run("DELETE FROM illnesses WHERE id = ? AND member_id = ?", (row_id, member_id))
    return to(request, "member", member_id=member_id)


# ── Прививки ─────────────────────────────────────────────────────────────

@router.post("/m/{member_id}/vac", name="vac_add")
def vac_add(request: Request, member_id: int, name: str = Form(""), done_on: str = Form(""),
            next_due: str = Form(""), notes: str = Form(""), csrf: str = Form("")):
    member_for(request, member_id, edit=True, csrf=csrf)
    if not name.strip():
        raise HTTPException(400, "Нужно название прививки")
    db.insert("INSERT INTO vaccines (member_id, name, done_on, next_due, notes, created_at) "
              "VALUES (?, ?, ?, ?, ?, ?)",
              (member_id, name.strip()[:200], _clean_day(done_on), _clean_day(next_due),
               notes.strip()[:2000], db.now()))
    return to(request, "member", member_id=member_id)


@router.post("/m/{member_id}/vac/{row_id}/delete", name="vac_delete")
def vac_delete(request: Request, member_id: int, row_id: int, csrf: str = Form("")):
    member_for(request, member_id, edit=True, csrf=csrf)
    db.run("DELETE FROM vaccines WHERE id = ? AND member_id = ?", (row_id, member_id))
    return to(request, "member", member_id=member_id)
