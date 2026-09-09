"""Точка входа приложения."""
import asyncio
import contextlib
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import config, db
from .routers import auth, chats, dashboard, projects, settings


async def _cleanup_loop() -> None:
    """Фоновая уборка: старые метрики, просроченные сессии, старые попытки входа."""
    while True:
        try:
            await asyncio.sleep(3600)
            keep = int(db.get_settings().get("metrics_keep_hours", "48"))
            db.execute(
                "DELETE FROM metrics_history WHERE at < now() - make_interval(hours => %s)",
                (max(1, min(keep, 720)),),
            )
            db.execute("DELETE FROM sessions WHERE expires_at < now()")
            db.execute("DELETE FROM login_attempts WHERE at < now() - interval '7 days'")
        except asyncio.CancelledError:
            raise
        except Exception:                              # noqa: BLE001
            # Уборка не должна ронять приложение
            pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_pool()
    db.apply_schema()
    db.seed()
    config.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    task = asyncio.create_task(_cleanup_loop())
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        db.close_pool()


app = FastAPI(
    title="Веб-интерфейс",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory=str(config.STATIC_DIR)), name="static")

app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(chats.router)
app.include_router(projects.router)
app.include_router(settings.router)


@app.get("/healthz", include_in_schema=False)
def healthz():
    """Проверка живости: и приложение, и база."""
    try:
        db.query_one("SELECT 1 AS ok")
        return {"status": "ok"}
    except Exception as exc:                           # noqa: BLE001
        return {"status": "error", "detail": str(exc)}
