"""Семейный анализатор здоровья: закрытый сайт, ставится на телефон как приложение."""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import auth, config, db, family, kopii, labs, organs
from .web import NeedLogin, current, page, to


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not config.SECRET_KEY:
        raise RuntimeError(f"нет SECRET_KEY в {config.ENV_FILE}")
    db.init()
    yield


app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(config.STATIC_DIR)), name="static")
app.include_router(auth.router)
app.include_router(family.router)
app.include_router(labs.router)
app.include_router(kopii.router)
app.include_router(organs.router)

CSP = ("default-src 'self'; img-src 'self' data: blob:; style-src 'self'; script-src 'self'; "
       "object-src 'none'; frame-src 'self'; frame-ancestors 'self'; base-uri 'none'; form-action 'self'")


@app.middleware("http")
async def headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("Content-Security-Policy", CSP)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    # no-referrer заставил бы браузер слать Origin: null — и формы не прошли бы проверку
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    # Приватные страницы не кладутся ни в какой кэш
    if not request.url.path.startswith("/static/"):
        resp.headers.setdefault("Cache-Control", "no-store")
    return resp


@app.exception_handler(NeedLogin)
def need_login(request: Request, exc: NeedLogin):
    if request.method == "GET":
        return to(request, "login_form")
    return HTMLResponse("<p>Нужно войти заново</p>", status_code=401)


@app.exception_handler(StarletteHTTPException)
def http_error(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 404 and request.method == "GET" and "/static/" not in request.url.path \
            and not current(request):
        return to(request, "login_form")
    return page(request, "error.html", {"sess": current(request), "message": exc.detail,
                                        "code": exc.status_code}, exc.status_code)


# ── Как приложение: описание, значки, работник ───────────────────────────

@app.get("/manifest.webmanifest", include_in_schema=False)
def manifest():
    root = config.ROOT_PATH
    return JSONResponse({
        "name": "Здоровье семьи", "short_name": "Здоровье",
        "start_url": f"{root}/", "scope": f"{root}/", "display": "standalone",
        "background_color": "#fff7f7", "theme_color": "#d62839", "lang": "ru",
        "icons": [
            {"src": f"{root}/static/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": f"{root}/static/icon-512.png", "sizes": "512x512", "type": "image/png"},
            {"src": f"{root}/static/icon-maskable-512.png", "sizes": "512x512", "type": "image/png",
             "purpose": "maskable"},
        ]}, media_type="application/manifest+json")


@app.get("/sw.js", include_in_schema=False)
def service_worker():
    # Работник лежит в корне сайта, чтобы его область — весь сайт
    return FileResponse(config.STATIC_DIR / "sw.js", media_type="text/javascript",
                        headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": f"{config.ROOT_PATH}/"})


@app.get("/healthz", include_in_schema=False)
def healthz():
    try:
        db.one("SELECT 1 AS ok")
        return {"status": "ok"}
    except Exception as exc:                                   # noqa: BLE001
        return JSONResponse({"status": "error", "detail": str(exc)}, status_code=500)

