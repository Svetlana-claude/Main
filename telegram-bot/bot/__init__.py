"""Телеграм-бот рабочего места.

Бот — **второй вход в то же рабочее место**, а не отдельная программа: движок,
база и таблица диалогов те же, что у `webui`. Поэтому пакет при импорте
добавляет в путь поиска каталог `webui/`: оттуда берутся драйвер Claude Code
(`app.services.claude_driver`) и настройки (`app.config`).

Делается это здесь, а не в каждом модуле, и до любого `import app.*`.
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]      # /home/mokeeva/main
WEBUI_DIR = REPO_ROOT / "webui"

if str(WEBUI_DIR) not in sys.path:
    sys.path.insert(0, str(WEBUI_DIR))
