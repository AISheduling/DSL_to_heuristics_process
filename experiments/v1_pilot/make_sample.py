"""
Выборка инстансов для первого эксперимента В1 (docs/adr/0003-v1-experiment-protocol.md).

    python experiments/v1_pilot/make_sample.py [--seed 2026] [--pilot 15]

Из каждого набора (J60, J120) берется по одному инстансу на каждую комбинацию параметров
генератора ProGen (J60 — 48, J120 — 60; номер инстанса из 1..10 — случайный при
фиксированном seed). Пилот — случайные `--pilot` инстансов выборки из каждого набора.
Для каждого инстанса записываются эталоны (src/references.py) и 12 индикаторов
(src/indicators.py), чтобы следующие шаги и разбор результатов не пересчитывали их.
Результат — experiments/v1_pilot/sample.json (в git, чтобы выборка не менялась).
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from indicators import flat_indicators  # noqa: E402
from psplib import instance_name, parse_sm_file, split_name  # noqa: E402
from references import RCPLIB_FILE, load_rcplib, load_references  # noqa: E402

SETS = {"j60": 48, "j120": 60}            # Набор -> число комбинаций параметров
INSTANCES_PER_PARAM = 10
OUTPUT = Path(__file__).resolve().parent / "sample.json"


def choose(seed: int, pilot_per_set: int) -> list[tuple[str, int, int, bool]]:
    """[(набор, параметр, инстанс, в пилоте)] — детерминированно по seed."""
    rng = random.Random(seed)
    chosen = []
    for set_name, n_params in SETS.items():
        picks = [(set_name, p, rng.randint(1, INSTANCES_PER_PARAM)) for p in range(1, n_params + 1)]
        pilot = set(rng.sample(range(n_params), pilot_per_set))
        chosen += [(*pick, i in pilot) for i, pick in enumerate(picks)]
    return chosen


def build_sample(seed: int, pilot_per_set: int, psplib_dir: Path) -> dict:
    rcplib = load_rcplib() if RCPLIB_FILE.exists() else None
    refs = {s: load_references(s, psplib_dir=psplib_dir, rcplib=rcplib, use_rcplib=rcplib is not None)
            for s in SETS}
    instances = []
    for set_name, param, inst, pilot in choose(seed, pilot_per_set):
        name = instance_name(set_name, param, inst)
        assert split_name(name) == (set_name, param, inst)
        data = parse_sm_file(psplib_dir / "instances" / set_name / f"{name}.sm")
        instances.append({
            "name": name, "set": set_name, "param": param, "instance": inst, "pilot": pilot,
            "reference": refs[set_name][name].as_dict(),
            "indicators": {k: round(v, 4) if isinstance(v, float) else v
                           for k, v in flat_indicators(data).items()},
        })
    return {
        "created": date.today().isoformat(),
        "seed": seed,
        "rule": (f"по одному инстансу на каждую комбинацию параметров ProGen "
                 f"({', '.join(f'{s}: {n}' for s, n in SETS.items())}); пилот — "
                 f"{pilot_per_set} случайных инстансов выборки из каждого набора"),
        "reference_sources": "PSPLIB solutions" + (" + RCPLIB v6" if rcplib else ""),
        "size": len(instances),
        "pilot_size": sum(i["pilot"] for i in instances),
        "instances": instances,
    }


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--pilot", type=int, default=15, help="инстансов пилота из каждого набора")
    args = parser.parse_args()
    sample = build_sample(args.seed, args.pilot, ROOT / "data" / "psplib")
    OUTPUT.write_text(json.dumps(sample, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{sample['size']} инстансов (пилот {sample['pilot_size']}) -> {OUTPUT}")
