"""
Маршрутизатор В2-LLM (ADR 0004): до вызова LLM считает метахарактеристику F1, сравнивает с
порогом и выбирает описание проекта. Уровни: b — без метаданных (как (б) В1), v — «вердикт»
(какие правила не брать), g — «свойство» (значение и смысл, без названий правил). Если
маршрутизатор не сработал, DSL уровней v и g совпадает с b.
"""
from __future__ import annotations

import json
from pathlib import Path

from dsl_builder import DIGITS, build_dsl
from rule_features import rule_features

ROOT = Path(__file__).resolve().parents[1]
TRIGGERS_FILE = ROOT / "experiments" / "v2_counterexamples" / "results" / "f1-grid" / "triggers.json"
TRIGGER_RULE = "LST"  # У MTS тот же признак и порог (triggers.json)

LEVELS = ("b", "v", "g")

# Тексты блоков зафиксированы в ADR 0004, п. 3; правка только с записью в ADR
VERDICT = {
    "avoid_rules": ["LST", "MTS"],
    "text": ("На этом проекте правила приоритета LST (первой ставится работа с самым "
             "ранним поздним стартом) и MTS (первой ставится работа с наибольшим числом "
             "всех последующих работ) дают заметно худший makespan. Не используй их."),
}
# Версия текстов блоков; пишется в манифест и файлы генераций (ADR 0004, п. 3 и 11)
ROUTER_VERSION = "v2-2026-11-10"
PROPERTY_MEANING = (
    "В проекте есть пары работ h и c, не связанных предшествованием, которые не помещаются "
    "на ресурс одновременно. Работа c лежит на критическом пути. Поздние сроки расходятся: "
    "поздний старт c раньше, чем у h (LS_c < LS_h), а поздний срок окончания h раньше, чем "
    "у c (LF_h < LF_c), — за h идут работы, которых ждет критический путь. Если поставить c "
    "раньше h, h ждет конца c, работы после h опаздывают, и вместе с ними опаздывает "
    "критический путь. Значение — сумма таких возможных опозданий (с учетом свободного "
    "ресурса рядом с c), деленная на длину критического пути. Выше порога свойство выражено "
    "и заметно влияет на makespan."
)


def load_trigger(path: Path = TRIGGERS_FILE, rule: str = TRIGGER_RULE) -> dict:
    """Признак, направление и порог правила из отчета fit_triggers.py."""
    t = json.loads(path.read_text(encoding="utf-8"))[rule]
    return {"feature": t["feature"], "direction": t["direction"], "threshold": t["threshold"]}


def decide(instance: dict, trigger: dict) -> dict:
    """Значение признака на проекте и сработал ли маршрутизатор."""
    value = rule_features(instance)[trigger["feature"]]
    t = trigger["threshold"]
    fired = value > t if trigger["direction"] == ">" else value < t
    return {"feature": trigger["feature"], "value": value, "threshold": t, "fired": bool(fired)}


def route_dsl(instance: dict, level: str, decision: dict) -> dict:
    """DSL уровня: состав none плюс блок уровня, если маршрутизатор сработал."""
    if level not in LEVELS:
        raise ValueError(f"unknown level {level!r}; expected one of {LEVELS}")
    dsl = build_dsl(instance, "none")
    if not decision["fired"] or level == "b":
        return dsl
    if level == "v":
        dsl["rule_guidance"] = {"avoid_rules": list(VERDICT["avoid_rules"]), "text": VERDICT["text"]}
    else:
        dsl["project_properties"] = {decision["feature"]: {
            "value": round(decision["value"], DIGITS),
            "threshold": round(decision["threshold"], DIGITS),
            "meaning": PROPERTY_MEANING,
        }}
    return dsl
