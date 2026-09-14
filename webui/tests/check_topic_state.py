"""Проверка: кружок состояния темы горит по делу.

Три места, где это ломается незаметно:

* тема с оборванным ответом (последняя запись — вопрос или ошибка) считается
  выполненной. Кружок зеленеет там, где работа не доведена, — а кнопку для
  того и завели, чтобы такие темы было видно из перечня;
* идущий прямо сейчас ответ не учитывается: тема горит зелёным, пока движок
  в ней работает;
* запрос за состоянием берёт роль не той записи (без привязки к теме или не
  последнюю) — цвета разъезжаются по всему перечню.

Стенд заводит свой проект с темами, проверяет и убирает за собой.

Запуск:  .venv/bin/python tests/check_topic_state.py
"""
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db                                     # noqa: E402
from app.routers import projects                       # noqa: E402
from app.services import runs                          # noqa: E402

# Тема -> записи в ней -> какого кружка ждём
CASES = [
    ("ответ получен",        ["user", "assistant"],          projects.TOPIC_DONE),
    ("вопрос без ответа",    ["user", "assistant", "user"],  projects.TOPIC_WORK),
    ("ответ оборвался",      ["user", "error"],              projects.TOPIC_WORK),
    ("пустая тема",          [],                             projects.TOPIC_EMPTY),
]


def _make_project() -> tuple[int, dict[str, int]]:
    # Slug уникален в таблице, а проектов стенд заводит два — своё имя каждому
    mark = uuid.uuid4().hex[:8]
    row = db.query_one(
        "INSERT INTO projects (name, slug, workdir) VALUES (%s, %s, %s) RETURNING id",
        (f"Стенд кружков {mark}", f"stend-dots-{mark}", "/tmp/stend-dots"),
    )
    project_id = row["id"]
    topic_ids: dict[str, int] = {}
    for title, roles, _ in CASES:
        topic = db.query_one(
            "INSERT INTO conversations (kind, project_id, title) "
            "VALUES ('topic', %s, %s) RETURNING id",
            (project_id, title),
        )
        topic_ids[title] = topic["id"]
        for role in roles:
            db.execute(
                "INSERT INTO messages (conversation_id, role, content) VALUES (%s, %s, %s)",
                (topic["id"], role, f"{role} в теме «{title}»"),
            )
    return project_id, topic_ids


def main() -> int:
    db.init_pool()
    project_id, topic_ids = _make_project()
    problems: list[str] = []
    try:
        got = projects._topics_state_map(project_id)

        if len(got) != len(CASES):
            problems.append(f"тем в ответе {len(got)} вместо {len(CASES)}")

        for title, _, expected in CASES:
            state = (got.get(str(topic_ids[title])) or {}).get("state")
            if state != expected:
                problems.append(f"«{title}»: {state} вместо {expected}")

        # Идущий ответ перекрашивает тему, даже если последняя запись — ответ
        done_id = topic_ids["ответ получен"]
        key = runs.key_of(projects.RUN_KIND, done_id)
        runs._runs[key] = runs.Run(key)
        try:
            live = projects._topics_state_map(project_id)[str(done_id)]["state"]
            if live != projects.TOPIC_WORK:
                problems.append(f"идущий ответ: {live} вместо {projects.TOPIC_WORK}")
        finally:
            del runs._runs[key]

        # Соседний проект не должен попадать в ответ
        other_id, other_topics = _make_project()
        try:
            mine = projects._topics_state_map(project_id)
            if any(str(tid) in mine for tid in other_topics.values()):
                problems.append("в ответ попали темы соседнего проекта")
        finally:
            db.execute("DELETE FROM projects WHERE id = %s", (other_id,))
    finally:
        db.execute("DELETE FROM projects WHERE id = %s", (project_id,))

    if problems:
        print("ПРОВАЛ:")
        for p in problems:
            print(" -", p)
        return 1

    print("OK: выполненное зелёное, незакрытое и идущее красное, пустое серое, "
          "чужие темы не мешаются")
    return 0


if __name__ == "__main__":
    sys.exit(main())
