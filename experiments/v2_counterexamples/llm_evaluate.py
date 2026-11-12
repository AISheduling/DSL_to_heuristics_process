from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from stats import holm, paired_wilcoxon  # noqa: E402

ALPHA = 0.05
DELTA = 0.5  # п. п., как в ADR 0003, п. 9
PRIMARY = (("v", "b"), ("g", "b"))


def read_runs(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["fired"] = r["fired"] == "True"
        r["s"] = float(r["s"])
        r["rpd_best"] = float(r["rpd_best"]) if r["status"] == "ok" else None
        r["not_worse_lft"] = r["not_worse_lft"] == "True" if r["status"] == "ok" else None
    return rows


def project_values(rows: list[dict]) -> dict[tuple[str, str], float]:
    """
    (проект, уровень) -> среднее RPD по допустимым генерациям;
    нет допустимых — нет ключа.
    """
    acc: dict[tuple[str, str], list[float]] = {}
    for r in rows:
        if r["rpd_best"] is not None:
            acc.setdefault((r["project"], r["level"]), []).append(r["rpd_best"])
    return {k: mean(v) for k, v in acc.items()}


def compare(values: dict, projects: list[str], x: str, y: str) -> dict:
    both = [p for p in projects if (p, x) in values and (p, y) in values]
    res = paired_wilcoxon([values[(p, x)] for p in both], [values[(p, y)] for p in both])
    return res | {"excluded": len(projects) - len(both)}


def _verdict(res: dict, p_key: str, y: str) -> str:
    if res["mean_diff"] is None or res[p_key] >= ALPHA or abs(res["mean_diff"]) < DELTA:
        return f"нет различия с {y}"
    return f"лучше {y}" if res["mean_diff"] < 0 else f"хуже {y}"


def evaluate(rows: list[dict]) -> dict:
    values = project_values(rows)
    info = {r["project"]: r for r in rows}
    fired = sorted(p for p, r in info.items() if r["fired"])
    every = sorted(info)

    primary = {f"{x}-{y}": compare(values, fired, x, y) for x, y in PRIMARY}
    adjusted = holm({k: v["p_value"] for k, v in primary.items()})
    for (x, y), (k, res) in zip(PRIMARY, primary.items()):
        res["p_holm"] = adjusted[k]
        res["verdict"] = _verdict(res, "p_holm", y)

    groups = {"сработавшие": fired, "все проекты": every}
    for env in sorted({r["env"] for r in info.values()}):
        groups[f"{env}, сработавшие"] = [p for p in fired if info[p]["env"] == env]
    alarms = [p for p in fired if info[p]["s"] == 0.0]
    if alarms:
        groups["ложные срабатывания (s = 0)"] = alarms
    secondary = {"g-v | сработавшие": compare(values, fired, "g", "v")}
    for name, projects in groups.items():
        if name == "сработавшие":
            continue
        for x, y in PRIMARY:
            secondary[f"{x}-{y} | {name}"] = compare(values, projects, x, y)
    for k, res in secondary.items():
        res["verdict"] = _verdict(res, "p_value", k.split("|")[0].strip().split("-")[1])

    levels = {}
    for level in ("b", "v", "g"):
        lv = [r for r in rows if r["level"] == level and r["fired"]]
        ok = [r for r in lv if r["rpd_best"] is not None]
        levels[level] = {"runs": len(lv), "valid": len(ok),
                         "mean_rpd": mean(r["rpd_best"] for r in ok) if ok else None,
                         "not_worse_lft": mean(float(r["not_worse_lft"]) for r in ok) if ok else None}
    lft = [100 * (float(info[p]["lft"]) - float(info[p]["best"])) / float(info[p]["best"]) for p in fired]
    return {"alpha": ALPHA, "delta": DELTA, "fired_projects": len(fired), "projects": len(every),
            "levels_fired": levels, "lft_rpd_fired": mean(lft) if lft else None,
            "primary": primary, "secondary": secondary}


def _f(x, d=2) -> str:
    return "—" if x is None else f"{x:.{d}f}"


def _p(x) -> str:
    return "—" if x is None else (f"{x:.1e}" if x < 0.001 else f"{x:.3f}")


def report(out: dict, source: str) -> str:
    lines = [f"# Оценка В2-LLM — `{source}`", "",
             f"Проект — единица сравнения; значение — среднее RPD к best_known по допустимым "
             f"генерациям. Разность x−y < 0 — x лучше. Двусторонний Уилкоксон; основные сравнения — "
             f"поправка Холма на 2, α = {out['alpha']}, δ = {out['delta']} п. п. (ADR 0004, п. 8).", "",
             f"Проектов: {out['projects']}, маршрутизатор сработал: {out['fired_projects']}.", "",
             "## Уровни на сработавших проектах (все генерации)", "",
             "| уровень | генераций | допустимых | средний RPD | не хуже LFT |", "|---|---|---|---|---|"]
    for level, s in out["levels_fired"].items():
        lines.append(f"| {level} | {s['runs']} | {s['valid']} | {_f(s['mean_rpd'])} | {_f(s['not_worse_lft'])} |")
    lines.append(f"| LFT (правило) | — | — | {_f(out['lft_rpd_fired'])} | 1.00 |")
    head = ("| сравнение | проектов | исключено | средняя разность | медиана | x лучше / y лучше / "
            "равны | p | {p2} | вывод |")
    lines += ["", "## Основные сравнения (сработавшие проекты, Холм)", "",
              head.format(p2="p (Холм)"), "|---|---|---|---|---|---|---|---|---|"]
    for k, r in out["primary"].items():
        lines.append(f"| {k} | {r['n']} | {r['excluded']} | {_f(r['mean_diff'])} | {_f(r['median_diff'])} | "
                     f"{r['x_better']} / {r['y_better']} / {r['ties']} | {_p(r['p_value'])} | "
                     f"{_p(r['p_holm'])} | {r['verdict']} |")
    lines += ["", "## Дополнительные сравнения (без поправки, без зачета)", "",
              head.format(p2="—"), "|---|---|---|---|---|---|---|---|---|"]
    for k, r in out["secondary"].items():
        # «|» в названии ломает таблицу markdown
        lines.append(f"| {k.replace(' | ', ', ')} | {r['n']} | {r['excluded']} | {_f(r['mean_diff'])} | {_f(r['median_diff'])} | "
                     f"{r['x_better']} / {r['y_better']} / {r['ties']} | {_p(r['p_value'])} | — | {r['verdict']} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> dict:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--runs", type=Path, required=True, help="runs.csv из llm_run_kernel.py")
    p.add_argument("--out", type=Path, help="папка для eval.md и eval.json (по умолчанию — рядом с runs.csv)")
    args = p.parse_args(argv)
    out_dir = args.out or args.runs.parent
    out = evaluate(read_runs(args.runs))
    (out_dir / "eval.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "eval.md").write_text(report(out, args.runs.parent.name), encoding="utf-8")
    for k, r in out["primary"].items():
        print(f"{k}: n={r['n']}, средняя разность {_f(r['mean_diff'])}, p(Холм) {_p(r['p_holm'])} — {r['verdict']}")
    return out


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
