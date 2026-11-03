from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from generators.traps import resource_blind_slack as f1  # noqa: E402

FAMILY = "F1"
SIZES = (30, 60, 120)
N_RES = (2, 4)
ENVS = ("isolated", "shared")
STRENGTHS = (0.0, 0.25, 0.5, 0.75, 1.0)
CONTROLS = f1.CONTROLS


def instance_hash(inst: dict) -> str:
    return hashlib.sha1(json.dumps(inst, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def instance_id(p: dict) -> str:
    return (f"{FAMILY}_{p['env']}_n{p['n']}_r{p['n_res']}_s{p['s']}_{p['control']}_seed{p['seed']}")


def build(p: dict) -> dict:
    """Проект по строке манифеста."""
    return f1.generate(p["n"], p["n_res"], s=p["s"], seed=p["seed"], control=p["control"],
                       shared=p["env"] == "shared")


def grid(seeds: int) -> list[dict]:
    rows = []
    for env in ENVS:
        for n in SIZES:
            for n_res in N_RES:
                for s in STRENGTHS:
                    for control in (CONTROLS[:1] if s == 1.0 else CONTROLS):
                        for seed in range(seeds):
                            rows.append({"family": FAMILY, "env": env, "n": n, "n_res": n_res,
                                         "s": s, "control": control, "seed": seed})
    return rows


def make_manifest(seeds: int) -> dict:
    instances = []
    for p in grid(seeds):
        inst = build(p)
        instances.append({"id": instance_id(p), **p, "hash": instance_hash(inst),
                          "target_rules": inst["generator"]["target_rules"]})
    return {"created": datetime.now().isoformat(timespec="seconds"), "family": FAMILY,
            "generator": f"generators.traps.{f1.NAME}", "seeds": seeds,
            "size": len(instances), "instances": instances}


def main(argv: list[str] | None = None) -> dict:
    parser = argparse.ArgumentParser(description="Сетка проектов В2 для ловушки F1 (описание: README.md).")
    parser.add_argument("--seeds", type=int, default=20)
    parser.add_argument("--out", type=Path, default=HERE / "instances.json")
    args = parser.parse_args(argv)
    manifest = make_manifest(args.seeds)
    args.out.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{manifest['size']} проектов -> {args.out}")
    return manifest


if __name__ == "__main__":
    main()
