"""Временный сайт для проверки редактора под входом: своя база и хранилище в /tmp,
настоящий сайт и его база не затрагиваются. Claude настоящий. Печатает пропуск входа и работает,
пока его не остановят."""
import os, sys, tempfile, time, threading
from pathlib import Path
T = Path(tempfile.mkdtemp(prefix="stend3d-"))
(T / "sekret").mkdir()  # отдельно: папка ключей закрыта для Claude, проекты рядом с ней быть не должны
(T / "sekret/t.env").write_text(f"SECRET_KEY=stend\nDB_PATH={T/'sekret/s.db'}\nLOGIN=Svetlana\nCHAT_DIR={T/'r'}\nPROJECTS_DIR={T/'p'}\nSEC_STATE={T/'sec'}\nTHUMB_DIR={T/'th'}\n")
os.environ.update(WEBUI2_ENV=str(T/"sekret/t.env"), ROOT_PATH="", WEBUI2_INSECURE_COOKIE="1")
W = Path(__file__).resolve().parents[3] / "webui2"
sys.path[:0] = [str(W), str(W/"tests")]
os.chdir(W)
import re, uvicorn
from fastapi.testclient import TestClient
from app import db, security
from app.main import app
S = "JBSWY3DPEHPK3PXP"; P = "ochen-dlinnyy-parol-1"
code = lambda d=0: security.totp_at(S, int(time.time()) // 30 + d)
hid = lambda h, n: re.search(rf'name="{n}" value="([^"]*)"', h).group(1)
with TestClient(app, headers={"origin": "http://testserver"}) as c:
    with db.tx() as con:
        con.execute("INSERT INTO setup (key, value) VALUES ('totp_secret', ?)", (S,))
    pg = c.get("/setup")
    c.post("/setup", data={"pre": hid(pg.text, "pre"), "password": P, "password2": P, "lock": "2468", "lock2": "2468", "code": code(-1)})
    pg = c.get("/login")
    r = c.post("/login", data={"pre": hid(pg.text, "pre"), "login": "Svetlana", "password": P})
    if "v2_session" not in c.cookies:
        c.post("/login/code", data={"code": code(), "pass_token": hid(r.text, "pass_token") if 'pass_token' in r.text else "", **{m: hid(r.text, m) for m in re.findall(r'type="hidden" name="(\w+)"', r.text)}})
    print(c.cookies.get("v2_session"), T, flush=True)
    c.get("/3d/")
    from app import konstruktor
    konstruktor.ensure_project()
uvicorn.run(app, host="127.0.0.1", port=8012, log_level="warning")
