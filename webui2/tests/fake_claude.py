#!/usr/bin/env python3
"""Подставной Claude для проверок: ведёт себя как настоящий в режиме потока
JSON на входе и выходе, но отвечает эхом и ничего не стоит.

Ответ — «Ответ: <сообщение>» с разметкой. В сообщении со словом «медленно»
куски идут с паузой, чтобы успеть дописать. «ошибка» — ответ с ошибкой.
Аргументы и окружение запуска пишутся в файл из FAKE_CLAUDE_LOG.

В теме проекта (есть --permission-mode) перед ответом «читает» CLAUDE.md —
так видна строка «Читаю…». Разовый запуск (--output-format json) — проверка
перед удалением проекта или само удаление (с bypassPermissions).
"""
import json
import os
import sys
import time
import uuid

args = sys.argv[1:]
session = args[args.index("--resume") + 1] if "--resume" in args else str(uuid.uuid4())
log = os.environ.get("FAKE_CLAUDE_LOG")
if log:
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"argv": args, "cwd": os.getcwd(),
                             "env": sorted(os.environ)}, ensure_ascii=False) + "\n")


def out(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


if args[args.index("--output-format") + 1] == "json":
    prompt = sys.stdin.read()
    if "bypassPermissions" in args:
        result = "Убрал службу fake-test.service.\nИТОГ: всё убрано"
    elif "nichego-vne" in os.getcwd():
        result = "Вне папки проекта ничего нет"
    else:
        result = "- служба fake-test.service\n- файл /etc/fake-test.conf"
    out({"type": "result", "is_error": False, "result": result, "session_id": session})
    sys.exit(0)

project = "--permission-mode" in args
out({"type": "system", "subtype": "init", "session_id": session, "tools": []})
for line in sys.stdin:
    try:
        msg = json.loads(line)
    except ValueError:
        continue
    text = msg["message"]["content"]
    slow = "медленно" in text
    if "ошибка" in text:
        out({"type": "result", "subtype": "error_during_execution", "is_error": True,
             "result": "сбой", "session_id": session, "usage": {}})
        continue
    if project:
        out({"type": "stream_event", "event": {"type": "message_start", "message": {"usage": {}}}})
        out({"type": "stream_event", "event": {"type": "content_block_delta",
             "delta": {"type": "text_delta", "text": "Сейчас гляну."}}})
        out({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Read",
             "input": {"file_path": os.path.join(os.getcwd(), "CLAUDE.md")}}]}})
        time.sleep(1.5 if slow else 0.01)
        if "создай" in text:
            with open("made-by-claude.txt", "w", encoding="utf-8") as fh:
                fh.write(text)
    out({"type": "stream_event", "event": {"type": "message_start",
         "message": {"usage": {"input_tokens": 1200, "cache_read_input_tokens": 3000}}}})
    answer = f"**Ответ:** {text}\n\n| а | б |\n|---|---|\n| 1 | 2 |\n\n<script>alert(1)</script>"
    for i in range(0, len(answer), 8):
        out({"type": "stream_event", "event": {"type": "content_block_delta",
             "delta": {"type": "text_delta", "text": answer[i:i + 8]}}})
        time.sleep(0.25 if slow else 0.005)
    out({"type": "assistant", "message": {"content": [{"type": "text", "text": answer}]}})
    out({"type": "result", "subtype": "success", "is_error": False, "result": answer,
         "session_id": session, "usage": {"input_tokens": 1200}})
