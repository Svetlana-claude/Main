#!/usr/bin/env python3
"""Подставной Claude для проверок: читает вопрос, отвечает разбором бланка.
Дата и гемоглобин берутся из имени файла-заглушки нет — из переменной FAKE_HB."""
import json
import os
import sys

prompt = sys.stdin.read()
mode = os.environ.get("FAKE_MODE", "ok")
if "Оцени по органам" in prompt:
    answer = {"general": "В целом спокойно, но печень стоит проверить.",
              "organs": {"liver": {"level": 2, "summary": "АЛТ заметно выше нормы",
                                   "questions": ["Были ли недавно лекарства или алкоголь?"],
                                   "suggestions": ["Пересдать АЛТ и АСТ через 2 недели", "Показаться терапевту"]},
                         "brain": {"level": None, "summary": "", "questions": ["Бывают ли головные боли?"],
                                   "suggestions": []},
                         "nonsense": {"level": 5}}}
elif mode == "empty":
    answer = {"date": "", "lab": "", "items": []}
else:
    answer = {"date": os.environ.get("FAKE_DATE", "2026-10-01"), "lab": "Тест-Лаб", "items": [
        {"name": "Гемоглобин", "value": float(os.environ.get("FAKE_HB", "105")), "value_text": "",
         "unit": "г/л", "low": 120, "high": 140, "ref_text": "120–140"},
        {"name": "Ферритин", "value": "45,5", "unit": "мкг/л", "low": 13, "high": 150, "ref_text": "13–150"},
        {"name": "Антитела к ВИЧ", "value": "отрицательно", "unit": "", "low": None, "high": None, "ref_text": ""},
    ]}
print(json.dumps({"type": "result", "is_error": False,
                  "result": "Вот разбор:\n```json\n" + json.dumps(answer, ensure_ascii=False) + "\n```"}))
