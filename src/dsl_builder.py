from __future__ import annotations

from indicators import STANDARD, flat_indicators

ACTIVITY = ("n",)
NETWORK = ("cnc", "os", "sp", "ad", "la", "i5", "tf")
RESOURCE = ("rf", "ru", "rs", "rc")

COMPOSITIONS: dict[str, tuple[str, ...]] = {
    "none": (),
    "network": ACTIVITY + NETWORK,
    "resource": ACTIVITY + RESOURCE,
    "all": ACTIVITY + NETWORK + RESOURCE,
}

DIGITS = 3
PROBLEM_ID = "RCPSP"


def build_dsl(instance: dict, composition: str = "all") -> dict:
    """DSL-словарь для одномодового RCPSP с возобновляемыми ресурсами, цель — makespan."""
    if composition not in COMPOSITIONS:
        raise ValueError(f"unknown composition {composition!r}; expected one of {list(COMPOSITIONS)}")
    dsl = {
        "project_id": PROBLEM_ID,
        "problem_statement": {
            "problem_type": "Single-mode RCPSP",
            "constraint_types": ["Precedence", "Resource Capacities"],
            "resource_nature": "Renewable",
            "execution_mode": "Single-Mode",
            "uncertainty": "Deterministic",
        },
        "optimization_objectives": {"primary": {"metric": "Makespan", "direction": "Minimize"}},
    }
    keys = COMPOSITIONS[composition]
    if keys:
        values = flat_indicators(instance)
        dsl["project_indicators"] = {
            "standard": STANDARD,
            "composition": composition,
            "values": {k: _round(values[k]) for k in keys},
        }
    return dsl


def _round(value):
    return round(value, DIGITS) if isinstance(value, float) else value
