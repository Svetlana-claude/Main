"""Копии на странице «Доступы»: когда была последняя и ключ, который скачивается один раз."""
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import FileResponse

from . import config
from .web import moment, need_owner, to

router = APIRouter()
COPIES = Path(os.environ.get("ZD_KOPII", Path.home() / "backups/zdorovye"))


def state() -> dict:
    copies = sorted(COPIES.glob("zdorovye-*.tar.gpg")) if COPIES.is_dir() else []
    last = None
    if copies:
        st = copies[-1].stat()
        last = {"when": moment(datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat()),
                "kb": max(1, st.st_size // 1024)}
    return {"key_waiting": config.KEY_FILE.is_file(), "last": last, "count": len(copies)}


@router.get("/kopii/klyuch", name="key_download")
def key_download(request: Request):
    need_owner(request)
    if not config.KEY_FILE.is_file():
        raise HTTPException(404, "Ключа на сервере уже нет — он у тебя")
    return FileResponse(config.KEY_FILE, media_type="application/octet-stream",
                        filename="zdorovye-klyuch-ot-kopiy.asc", headers={"Cache-Control": "no-store"})


@router.post("/kopii/klyuch/ubrat", name="key_forget")
def key_forget(request: Request, sure: str = Form(""), csrf: str = Form("")):
    need_owner(request, csrf)
    if sure != "да":
        raise HTTPException(400, "Сначала сохрани ключ и поставь галочку")
    config.KEY_FILE.unlink(missing_ok=True)
    return to(request, "access_page")
