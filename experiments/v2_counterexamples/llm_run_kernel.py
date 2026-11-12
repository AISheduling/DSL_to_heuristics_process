from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "experiments" / "runners"))
sys.path.insert(0, str(HERE))

import runner_common as rc  # noqa: E402
from llm_generate import GENERATIONS_DIR, LEVELS, SAMPLE_FILE, build  # noqa: E402
from metrics import rpd  # noqa: E402

RESULTS_DIR = HERE / "results"
RUN_COLUMNS = ["project", "env", "n", "s", "seed", "fired", "value", "level", "gen", "copied",
               "method", "status", "makespan", "best", "rpd_best", "lft", "lst", "vs_lft",
               "not_worse_lft", "invalid_select_count", "allocate_violations", "elapsed_s", "error"]


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _write_csv(path: Path, rows: list[dict], columns: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def _tail(text: str, limit: int = 400) -> str:
    return text if len(text) <= limit else "…" + text[-limit:]


def load_reference(ref_dir: Path) -> dict[str, dict]:
    """Проект -> best_known и makespan правил из прогона run_rules.py."""
    out = {r["id"]: {"best": int(r["best"]), "hash": r["hash"], "rules": {}}
           for r in read_csv(ref_dir / "instances.csv")}
    for r in read_csv(ref_dir / "rules.csv"):
        if r["id"] in out:
            out[r["id"]]["rules"][r["rule"]] = int(r["makespan"])
    return out


def run_generation(rec: dict, row: dict, ref: dict, timeout: float) -> dict:
    out = {"project": row["id"], "env": row["env"], "n": row["n"], "s": row["s"],
           "seed": row["seed"], "fired": row["fired"], "value": round(row["value"], 4),
           "level": rec["level"], "gen": rec["gen"], "copied": "copied_from" in rec,
           "method": rec.get("method"), "best": ref["best"], "lft": ref["rules"]["LFT"],
           "lst": ref["rules"]["LST"], "makespan": None}
    if rec.get("error"):
        return out | {"status": "generation_error", "error": _tail(rec["error"])}
    res = rc.run_skeleton(rec["select_job_fn"], rec["allocate_fn"], rec["dsl"], build(row),
                          timeout=timeout, shared_namespace=True)
    out |= {"status": res["status"], "error": _tail(res.get("error") or ""),
            "invalid_select_count": res.get("invalid_select_count"),
            "allocate_violations": res.get("allocate_violations"), "elapsed_s": res.get("elapsed_s")}
    if res["status"] == "ok":
        ms = res["makespan"]
        out |= {"makespan": ms, "rpd_best": round(rpd(ms, ref["best"]), 4),
                "vs_lft": round(rpd(ms, ref["rules"]["LFT"]), 4), "not_worse_lft": ms <= ref["rules"]["LFT"]}
    return out


def _mean(xs: list[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def stats(rows: list[dict]) -> dict:
    ok = [r for r in rows if r["status"] == "ok"]
    return {"runs": len(rows), "valid": len(ok),
            "mean_rpd_best": _mean([r["rpd_best"] for r in ok]),
            "not_worse_lft": _mean([float(r["not_worse_lft"]) for r in ok]),
            "statuses": dict(Counter(r["status"] for r in rows))}


def summarize(runs: list[dict]) -> dict:
    out: dict = {"levels": {}, "fired": {}, "not_fired": {}, "cells": {}}
    for level in LEVELS:
        lv = [r for r in runs if r["level"] == level]
        out["levels"][level] = stats(lv)
        out["fired"][level] = stats([r for r in lv if r["fired"]])
        out["not_fired"][level] = stats([r for r in lv if not r["fired"]])
        for env in sorted({r["env"] for r in lv}):
            for s in sorted({r["s"] for r in lv}):
                cell = [r for r in lv if r["env"] == env and r["s"] == s]
                out["cells"][f"{level}|{env}|{s}"] = stats(cell)
    return out


def _f(x, digits=2) -> str:
    return "—" if x is None else f"{x:.{digits}f}"


def report(run: str, runs: list[dict], refs: dict, rows: list[dict], summary: dict) -> str:
    lines = [f"# В2-LLM — запуск `{run}`", "",
             "RPD — отклонение makespan от best_known проекта, %, по допустимым генерациям. "
             "«Не хуже LFT» — доля допустимых генераций с makespan ≤ LFT на том же проекте. "
             "Уровни: b — без метаданных, v — вердикт, g — свойство (ADR 0004).", "",
             "## Маршрутизатор", "", "| окружение | s | проектов | сработал |", "|---|---|---|---|"]
    for env in sorted({r["env"] for r in rows}):
        for s in sorted({r["s"] for r in rows}):
            cell = [r for r in rows if r["env"] == env and r["s"] == s]
            lines.append(f"| {env} | {s} | {len(cell)} | {sum(r['fired'] for r in cell)} |")
    for title, key in (("Проекты, где маршрутизатор сработал", "fired"),
                       ("Проекты, где не сработал (v и g — копии b)", "not_fired")):
        lines += ["", f"## {title}", "", "| уровень | генераций | допустимых | RPD | не хуже LFT | статусы |",
                  "|---|---|---|---|---|---|"]
        for level, s in summary[key].items():
            lines.append(f"| {level} | {s['runs']} | {s['valid']} | {_f(s['mean_rpd_best'])} | "
                         f"{_f(s['not_worse_lft'])} | {s['statuses']} |")
    lines += ["", "## По ячейкам: RPD (допустимых / генераций)", "",
              "| окружение | s | b | v | g | LFT | LST |", "|---|---|---|---|---|---|---|"]
    for env in sorted({r["env"] for r in rows}):
        for s in sorted({r["s"] for r in rows}):
            cells = [summary["cells"].get(f"{lv}|{env}|{s}") for lv in LEVELS]
            proj = [r["id"] for r in rows if r["env"] == env and r["s"] == s]
            rule = {k: _mean([rpd(refs[p]["rules"][k], refs[p]["best"]) for p in proj]) for k in ("LFT", "LST")}
            text = " | ".join(f"{_f(c['mean_rpd_best'])} ({c['valid']}/{c['runs']})" if c else "—" for c in cells)
            lines.append(f"| {env} | {s} | {text} | {_f(rule['LFT'])} | {_f(rule['LST'])} |")
    lines += ["", "## Методы (названия из ответа модели), проекты со срабатыванием", ""]
    for level in LEVELS:
        top = Counter((r["method"] or "—") for r in runs if r["level"] == level and r["fired"]
                      and not r["copied"]).most_common(6)
        lines.append(f"- **{level}**: " + "; ".join(f"{m} — {k}" for m, k in top))
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> dict:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--run", required=True, help="папка generations/<run>")
    p.add_argument("--ref", required=True, help="папка results/<ref> прогона run_rules.py по выборке")
    p.add_argument("--timeout", type=float, default=rc.TIMEOUT_SECONDS)
    p.add_argument("--sample", type=Path, default=SAMPLE_FILE)
    p.add_argument("--generations", type=Path, default=GENERATIONS_DIR)
    p.add_argument("--results-dir", type=Path, default=RESULTS_DIR)
    args = p.parse_args(argv)

    sample = {r["id"]: r for r in json.loads(args.sample.read_text(encoding="utf-8"))["instances"]}
    refs = load_reference(args.results_dir / args.ref)
    files = sorted((args.generations / args.run).glob("*__*__g*.json"))
    if not files:
        raise SystemExit(f"нет генераций в {args.generations / args.run}")
    runs = []
    for i, path in enumerate(files, 1):
        rec = json.loads(path.read_text(encoding="utf-8"))
        row = sample[rec["project"]]
        if refs[row["id"]]["hash"] != row["hash"]:
            raise SystemExit(f"{row['id']}: хэш эталона не совпадает с выборкой")
        runs.append(run_generation(rec, row, refs[row["id"]], args.timeout))
        print(f"  [{i}/{len(files)}] {path.name}: {runs[-1]['status']}")
    rows = [sample[i] for i in sorted({r["project"] for r in runs})]
    summary = {"run": args.run, "ref": args.ref, "created": datetime.now().isoformat(timespec="seconds"),
               "projects": len(rows), "generations": len(runs), **summarize(runs)}
    out_dir = args.results_dir / args.run
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(out_dir / "runs.csv", runs, RUN_COLUMNS)
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "report.md").write_text(report(args.run, runs, refs, rows, summary), encoding="utf-8")
    for level, s in summary["fired"].items():
        print(f"Уровень {level}, сработавшие: допустимых {s['valid']}/{s['runs']}, "
              f"RPD {_f(s['mean_rpd_best'])}, не хуже LFT {_f(s['not_worse_lft'])}")
    print(f"Результаты: {out_dir}")
    return summary


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
