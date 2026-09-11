"""Проверка: окошко «Файлы проекта» показывает папку выдачи и только её.

Три места, где это ломается заметно или опасно:

* показан весь рабочий каталог — среди сотен файлов кода нужный не найти,
  а ровно за этим кнопку и открывают;
* в список попали `.env`, `.git`, `.venv` — «скачать» рядом с `.env`
  означает отдачу ключей;
* путь из запроса не проверен: `?path=../../.config/webui/webui.env`
  отдаёт `SECRET_KEY` и пароль базы.

Запуск:  .venv/bin/python tests/check_project_tree.py
"""
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.routers import projects                     # noqa: E402


def _make_tree(workdir: Path, downloads: Path, outside: Path) -> None:
    """Каталог проекта: код в рабочей части, выдача в своей папке."""
    # Рабочая часть: в окошке ничего этого быть не должно
    (workdir / "main.py").write_text("код", encoding="utf-8")
    (workdir / "app").mkdir()
    (workdir / "app" / "config.py").write_text("код", encoding="utf-8")

    # Папка выдачи: то, что просили сделать
    (downloads / "webclaude.md").write_text("свод", encoding="utf-8")
    (downloads / "макеты").mkdir()
    (downloads / "макеты" / "главная.png").write_bytes(b"PNG")

    # Сюда же могло попасть закрытое — не показываем и не отдаём
    (downloads / ".env").write_text("SECRET_KEY=xxx", encoding="utf-8")
    (downloads / "server.key").write_text("ключ", encoding="utf-8")
    (downloads / ".git").mkdir()
    (downloads / ".git" / "config").write_text("[core]", encoding="utf-8")
    (downloads / "__pycache__").mkdir()
    (downloads / "__pycache__" / "app.cpython-312.pyc").write_bytes(b"\x00")

    # Символьная ссылка наружу: в списке её быть не должно, иначе строка
    # обещает файл, который при скачивании всё равно будет отбит
    (downloads / "ссылка.txt").symlink_to(outside)

    # Свежий файл должен оказаться первым
    time.sleep(0.02)
    os.utime(downloads / "webclaude.md", None)


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp).resolve()
        outside = base / "секреты.env"
        outside.write_text("SECRET_KEY=наружу", encoding="utf-8")

        workdir = base / "project"
        workdir.mkdir()

        downloads = projects._downloads_dir(workdir)
        if downloads != workdir / "downloads" or not downloads.is_dir():
            print(f"ПРОВАЛ: папка выдачи не заведена, получено {downloads}")
            return 1

        _make_tree(workdir, downloads, outside)

        rows, truncated = projects._tree_entries(downloads)
        shown = {r["path"] for r in rows}

        expected = {"webclaude.md", str(Path("макеты") / "главная.png")}
        missing = expected - shown
        if missing:
            print("ПРОВАЛ: в списке нет файлов выдачи:", ", ".join(sorted(missing)))
            return 1

        forbidden = {
            "main.py": "файл рабочего каталога, а не выдачи",
            str(Path("app") / "config.py"): "файл рабочего каталога, а не выдачи",
            ".env": "файл настроек",
            "server.key": "закрытый ключ",
            str(Path(".git") / "config"): "служебное из .git",
            str(Path("__pycache__") / "app.cpython-312.pyc"): "скомпилированное",
            "ссылка.txt": "символьная ссылка наружу",
        }
        leaked = [f"{path} ({why})" for path, why in forbidden.items() if path in shown]
        if leaked:
            print("ПРОВАЛ: в списке оказалось лишнее:", "; ".join(leaked))
            return 1

        if len(shown) != len(expected):
            print(f"ПРОВАЛ: в списке {len(shown)} файлов вместо {len(expected)}:",
                  ", ".join(sorted(shown)))
            return 1
        if truncated:
            print("ПРОВАЛ: список из двух файлов объявлен обрезанным")
            return 1
        if rows[0]["path"] != "webclaude.md":
            print(f"ПРОВАЛ: порядок не по свежести, первым идёт {rows[0]['path']}")
            return 1
        if rows[0]["size"] != len("свод".encode("utf-8")):
            print("ПРОВАЛ: размер файла посчитан неверно")
            return 1

        # Путь из запроса: за папку выдачи выпускать нельзя ни одним способом
        escapes = {
            "../main.py": "выход в рабочий каталог",
            "../../секреты.env": "выход за пределы проекта",
            "макеты/../../main.py": ".. в середине пути",
            str(outside): "абсолютный путь",
            "ссылка.txt": "символьная ссылка наружу",
            "": "пустой путь — это сама папка",
        }
        for attempt, why in escapes.items():
            try:
                got = projects._resolve_in_dir(downloads, attempt)
            except ValueError:
                continue
            print(f"ПРОВАЛ: {why} — путь {attempt!r} пропущен как {got}")
            return 1

        inside = projects._resolve_in_dir(downloads, "макеты/главная.png")
        if inside != (downloads / "макеты" / "главная.png").resolve():
            print("ПРОВАЛ: обычный путь внутри папки выдачи не разобран")
            return 1

        # То же решение принимается и при скачивании: скрытое из списка
        # не должно забираться прямой ссылкой
        hidden = projects._resolve_in_dir(downloads, ".git/config")
        if projects._tree_visible(downloads.resolve(), hidden):
            print("ПРОВАЛ: скрытый из списка файл отдаётся по прямой ссылке")
            return 1

    print("OK: показана только папка выдачи, порядок по свежести, выход из неё отбит")
    return 0


if __name__ == "__main__":
    sys.exit(main())
