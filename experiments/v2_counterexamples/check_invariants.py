from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean, median

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from stats import holm, paired_wilcoxon, spearman  # noqa: E402

RESULTS_DIR = HERE / "results"
TARGET_RULES = ("LST", "MTS")
IMMUNE_RULE = "LFT"
DELTA_LOSS = 5.0
CONTROL_MAX = 1.0
ALPHA = 0.05
CONTROLS = ("fits", "short_delay")


def _read(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def load(run_dir: Path) -> list[dict]:
    """Строки «проект × правило» с параметрами проекта."""
    inst = {r["id"]: r for r in _read(run_dir / "instances.csv")}
    rows = []
    for r in _read(run_dir / "rules.csv"):
        p = inst[r["id"]]
        rows.append({"id": r["id"], "rule": r["rule"], "env": p["env"], "n": int(p["n"]),
                     "n_res": int(p["n_res"]), "s": float(p["s"]), "control": p["control"],
                     "seed": int(p["seed"]), "gap": float(r["gap_vs_others"]),
                     "rpd_best": float(r["rpd_best"]), "chain_delay": int(r["chain_delay"]),
                     "unavoidable": int(r["unavoidable_delay"]), "best": int(p["best"]),
                     "lb": int(p["lb"]), "optimal": p["optimal"] == "True"})
    return rows


def _in_control(row: dict, control: str) -> bool:
    return row["control"] == control or row["s"] == 1.0


def check_cell(rows: list[dict], rule: str) -> dict:
    """Числа критериев для одной ячейки; p-значения — до поправки."""
    by = {(r["id"], r["rule"]): r for r in rows}
    ids = sorted({r["id"] for r in rows})
    strong = [i for i in ids if by[(i, rule)]["s"] >= 0.5]
    out = {"n_projects": len(ids),
           "c1_median_gap": median(by[(i, rule)]["gap"] for i in strong),
           "c2": paired_wilcoxon([by[(i, rule)]["rpd_best"] for i in strong],
                                 [by[(i, IMMUNE_RULE)]["rpd_best"] for i in strong]),
           "c3": {}, "c4_median_gap": {}}
    for c in CONTROLS:
        sel = [by[(i, rule)] for i in ids if _in_control(by[(i, rule)], c)]
        out["c3"][c] = spearman([r["s"] for r in sel], [r["gap"] for r in sel])
        out["c4_median_gap"][c] = median(r["gap"] for r in sel if r["s"] == 0.0)
    return out


def dose_table(rows: list[dict], rule: str) -> dict:
    """Медиана gap_vs_others(R) по s для каждого (окружение, n), все n_res и контроли вместе."""
    acc = defaultdict(list)
    for r in rows:
        if r["rule"] == rule:
            acc[(r["env"], r["n"], r["s"])].append(r["gap"])
    return {f"{e}|{n}|{s}": median(v) for (e, n, s), v in sorted(acc.items())}


def chain_share(rows: list[dict], rule: str) -> dict:
    """Доля проектов, где цепочка у правила опоздала сверх неизбежного: с ловушками и без."""
    acc = defaultdict(lambda: [0, 0])
    for r in rows:
        if r["rule"] == rule:
            key = (r["env"], "trap" if r["s"] > 0 else "control")
            acc[key][0] += r["chain_delay"] > r["unavoidable"]
            acc[key][1] += 1
    return {f"{e}|{k}": a / b for (e, k), (a, b) in sorted(acc.items())}


def reference_quality(rows: list[dict]) -> dict:
    per = {r["id"]: r for r in rows}
    return {"projects": len(per),
            "share_optimal": mean(r["optimal"] for r in per.values()),
            "median_gap_best_lb": median(100 * (r["best"] - r["lb"]) / r["lb"] for r in per.values())}


def psplib_summary(path: Path) -> dict | None:
    if not path.exists():
        return None
    acc = defaultdict(list)
    for r in _read(path):
        acc[r["rule"]].append(float(r["gap_vs_others"]))
    return {rule: {"n": len(v), "median_gap": median(v), "mean_gap": mean(v),
                   "share_over_1pp": mean(x > 1 for x in v)} for rule, v in sorted(acc.items())}


def build_report(run_dir: Path) -> dict:
    rows = load(run_dir)
    cells = defaultdict(list)
    for r in rows:
        cells[(r["env"], r["n"], r["n_res"])].append(r)
    results, p_values = {}, {}
    for (env, n, n_res), cell_rows in sorted(cells.items()):
        for rule in TARGET_RULES:
            key = f"{env}|{n}|{n_res}|{rule}"
            res = check_cell(cell_rows, rule)
            results[key] = res
            p_values[f"{key}|c2"] = res["c2"]["p_value"]
            for c in CONTROLS:
                p_values[f"{key}|c3|{c}"] = res["c3"][c]["p_value"]
    adjusted = holm(p_values)
    for key, res in results.items():
        res["c2"]["p_holm"] = adjusted[f"{key}|c2"]
        for c in CONTROLS:
            res["c3"][c]["p_holm"] = adjusted[f"{key}|c3|{c}"]
        res["pass"] = {
            "c1": res["c1_median_gap"] >= DELTA_LOSS,
            "c2": res["c2"]["mean_diff"] > 0 and res["c2"]["p_holm"] < ALPHA,
            "c3": all((res["c3"][c]["rho"] or 0) > 0 and res["c3"][c]["p_holm"] < ALPHA for c in CONTROLS),
            "c4": all(res["c4_median_gap"][c] < CONTROL_MAX for c in CONTROLS),
        }
        res["confirmed"] = all(res["pass"].values())
    return {"run": run_dir.name,
            "criteria": {"target_rules": TARGET_RULES, "immune_rule": IMMUNE_RULE,
                         "delta_loss": DELTA_LOSS, "control_max": CONTROL_MAX, "alpha": ALPHA},
            "cells": results,
            "dose": {rule: dose_table(rows, rule) for rule in TARGET_RULES + (IMMUNE_RULE,)},
            "chain_late_share": {rule: chain_share(rows, rule) for rule in TARGET_RULES + (IMMUNE_RULE,)},
            "reference": reference_quality(rows),
            "psplib": psplib_summary(run_dir / "psplib_rules.csv")}


def _mark(ok: bool) -> str:
    return "да" if ok else "**нет**"


def to_markdown(rep: dict) -> str:
    c = rep["criteria"]
    lines = [f"# Проверка инварианта F1 — запуск `{rep['run']}`", "",
             f"Целевые правила: {', '.join(c['target_rules'])}; защищенное правило: {c['immune_rule']}.",
             f"C1: медиана проигрыша при s ≥ 0.5 ≥ {c['delta_loss']} п. п.; C2: хуже {c['immune_rule']} "
             f"(Уилкоксон, Холм, α = {c['alpha']}); C3: Спирмен(s, проигрыш) > 0 при обоих контролях; "
             f"C4: при s = 0 медиана проигрыша < {c['control_max']} п. п.", "",
             "Проигрыш — gap_vs_others: makespan правила к лучшему из остальных правил на том же проекте, %.",
             "", "## Критерии по ячейкам", "",
             "| окружение | n | n_res | правило | проектов | C1 медиана | C2 Δ rpd, p | C3 ρ fits / short | "
             "C4 fits / short | C1 | C2 | C3 | C4 | итог |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for key, r in rep["cells"].items():
        env, n, n_res, rule = key.split("|")
        rho = " / ".join("—" if r["c3"][k]["rho"] is None else f"{r['c3'][k]['rho']:.2f}" for k in CONTROLS)
        c4 = " / ".join(f"{r['c4_median_gap'][k]:.1f}" for k in CONTROLS)
        p = r["pass"]
        lines.append(f"| {env} | {n} | {n_res} | {rule} | {r['n_projects']} | {r['c1_median_gap']:.1f} | "
                     f"{r['c2']['mean_diff']:.1f}, {r['c2']['p_holm']:.1e} | {rho} | {c4} | "
                     f"{_mark(p['c1'])} | {_mark(p['c2'])} | {_mark(p['c3'])} | {_mark(p['c4'])} | "
                     f"{'подтверждено' if r['confirmed'] else '**нет**'} |")
    lines += ["", "## Доза — ответ: медиана проигрыша по s, %", ""]
    for rule, table in rep["dose"].items():
        groups = defaultdict(dict)
        for key, v in table.items():
            env, n, s = key.split("|")
            groups[(env, int(n))][float(s)] = v
        strengths = sorted({s for g in groups.values() for s in g})
        lines += [f"**{rule}**", "", "| окружение | n | " + " | ".join(f"s = {s}" for s in strengths) + " |",
                  "|---|---|" + "---|" * len(strengths)]
        for (env, n), g in sorted(groups.items()):
            lines.append(f"| {env} | {n} | " + " | ".join(f"{g[s]:.1f}" for s in strengths) + " |")
        lines.append("")
    lines += ["## Опоздание цепочки сверх неизбежного (доля проектов)", "",
              "| правило | окружение | с ловушками (s > 0) | контроль (s = 0) |", "|---|---|---|---|"]
    for rule, t in rep["chain_late_share"].items():
        for env in sorted({k.split("|")[0] for k in t}):
            lines.append(f"| {rule} | {env} | {t.get(f'{env}|trap', 0):.2f} | {t.get(f'{env}|control', 0):.2f} |")
    ref = rep["reference"]
    lines += ["", "## Эталон", "",
              f"Проектов: {ref['projects']}; доказанный оптимум (best = LB): {ref['share_optimal']:.1%}; "
              f"медиана разрыва best/LB: {ref['median_gap_best_lb']:.1f}%.", ""]
    if rep["psplib"]:
        lines += ["## PSPLIB, выборка В1 (справочно)", "",
                  "| правило | инстансов | медиана проигрыша | среднее | доля > 1 п. п. |", "|---|---|---|---|---|"]
        for rule, v in rep["psplib"].items():
            lines.append(f"| {rule} | {v['n']} | {v['median_gap']:.1f} | {v['mean_gap']:.1f} | {v['share_over_1pp']:.0%} |")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> dict:
    parser = argparse.ArgumentParser(description="Проверка инварианта F1 по критериям C1–C4 (описание: README.md).")
    parser.add_argument("--run", required=True)
    parser.add_argument("--results-dir", type=Path, default=RESULTS_DIR)
    args = parser.parse_args(argv)
    run_dir = args.results_dir / args.run
    rep = build_report(run_dir)
    (run_dir / "invariants.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    (run_dir / "invariants.md").write_text(to_markdown(rep), encoding="utf-8")
    confirmed = sum(r["confirmed"] for r in rep["cells"].values())
    print(f"подтверждено ячеек: {confirmed}/{len(rep['cells'])} -> {run_dir / 'invariants.md'}")
    return rep


if __name__ == "__main__":
    main()
