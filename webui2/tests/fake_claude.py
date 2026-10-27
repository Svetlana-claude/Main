#!/usr/bin/env python3
"""Подставной Claude для проверок: ведёт себя как настоящий в режиме потока
JSON на входе и выходе, но отвечает эхом и ничего не стоит.

Ответ — «Ответ: <сообщение>» с разметкой. В сообщении со словом «медленно»
куски идут с паузой, чтобы успеть дописать. «ошибка» — ответ с ошибкой.
Аргументы и окружение запуска пишутся в файл из FAKE_CLAUDE_LOG.
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
