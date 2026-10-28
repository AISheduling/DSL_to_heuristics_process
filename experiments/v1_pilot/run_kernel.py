from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "experiments" / "runners"))

import runner_common as rc  # noqa: E402
import scheduler_skeleton as sched  # noqa: E402
from dsl_builder import build_dsl  # noqa: E402
from metrics import rpd, summarize_rpd  # noqa: E402
from priority_rules import RULES  # noqa: E402
from psplib import parse_sm_file  # noqa: E402
from schedule_checker import validate_schedule  # noqa: E402

SAMPLE_FILE = HERE / "sample.json"
GENERATIONS_DIR = HERE / "generations"
RESULTS_DIR = HERE / "results"
PSPLIB_INSTANCES = ROOT / "data" / "psplib" / "instances"

RUN_COLUMNS = ["instance", "set", "param", "level", "gen", "method", "status", "generation_error",
               "makespan", "bks", "lb", "cpm", "optimal", "rpd_bks", "rpd_cpm",
               "invalid_select_count", "allocate_violations", "kernel_status",
               "uses_indicators", "elapsed_s", "error"]
BASELINE_COLUMNS = ["instance", "set", "param", "rule", "status", "makespan", "bks", "lb", "cpm",
                    "optimal", "rpd_bks", "rpd_cpm"]


def generation_files(run_dir: Path) -> list[Path]:
    return sorted(p for p in run_dir.glob("*__*__g*.json"))


def _tail(text: str, limit: int = 400) -> str:
    """Конец сообщения: у traceback причина в последних строках."""
    return text if len(text) <= limit else "…" + text[-limit:]


def _reference_fields(ref: dict, makespan) -> dict:
    return {"bks": ref["bks"], "lb": ref["lb"], "cpm": ref["cpm"], "optimal": ref["optimal"],
            "rpd_bks": round(rpd(makespan, ref["bks"]), 4) if makespan is not None else None,
            "rpd_cpm": round(rpd(makespan, ref["cpm"]), 4) if makespan is not None else None}


def run_generation(rec: dict, info: dict, instance: dict, timeout: float) -> dict:
    row = {"instance": rec["instance"], "set": info["set"], "param": info["param"],
           "level": rec["level"], "gen": rec["gen"], "method": rec.get("method")}
    if rec.get("error"):
        row.update({"status": "generation_error", "generation_error": rec["error"].split(":")[0],
                    "error": _tail(rec["error"]), "makespan": None,
                    **_reference_fields(info["reference"], None)})
        return row
    code = (rec["select_job_fn"] or "") + (rec["allocate_fn"] or "")
    out = rc.run_skeleton(rec["select_job_fn"], rec["allocate_fn"], rec["dsl"], instance,
                          timeout=timeout, shared_namespace=True)
    makespan = out.get("makespan") if out["status"] == "ok" else None
    row.update({
        "status": out["status"], "generation_error": None, "makespan": makespan,
        **_reference_fields(info["reference"], makespan),
        "invalid_select_count": out.get("invalid_select_count"),
        "allocate_violations": out.get("allocate_violations"),
        "kernel_status": out.get("kernel_status"),
        "uses_indicators": "meta.indicators" in code,
        "elapsed_s": out.get("elapsed_s"),
        "error": _tail(out.get("error") or ""),
    })
    return row


def run_baselines(info: dict, instance: dict) -> list[dict]:
    """
    Встроенное правило и LFT/LST/MTS;
    код доверенный, поэтому без отдельного процесса.
    """
    rows = []
    dsl = build_dsl(instance, "none")
    for name, select in [("builtin", sched.default_select), *RULES.items()]:
        _, state = sched.build_state(dsl, instance)
        res = sched.run_schedule(state, select, sched.default_allocate)
        check = validate_schedule(instance, res["schedule"])
        ok = check["status"] == "valid" and res["status"] == "complete"
        makespan = check["makespan"] if ok else None
        rows.append({"instance": info["name"], "set": info["set"], "param": info["param"],
                     "rule": name, "status": "ok" if ok else check["status"], "makespan": makespan,
                     **_reference_fields(info["reference"], makespan)})
    return rows


def summarize(runs: list[dict], baselines: list[dict]) -> dict:
    out: dict = {"levels": {}, "rules": {}}
    for level in sorted({r["level"] for r in runs}):
        rows = [r for r in runs if r["level"] == level]
        s = summarize_rpd([r["makespan"] for r in rows], [r["bks"] for r in rows])
        s["statuses"] = _count(r["status"] for r in rows)
        s["uses_indicators"] = sum(1 for r in rows if r.get("uses_indicators"))
        out["levels"][level] = s
    for rule in sorted({b["rule"] for b in baselines}):
        rows = [b for b in baselines if b["rule"] == rule]
        out["rules"][rule] = summarize_rpd([b["makespan"] for b in rows], [b["bks"] for b in rows])
    return out


def _count(values) -> dict:
    counts: dict = {}
    for v in values:
        counts[v] = counts.get(v, 0) + 1
    return counts


def _write_csv(path: Path, rows: list[dict], columns: list[str]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def main(argv: list[str] | None = None) -> dict:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--run", required=True, help="папка generations/<run>")
    p.add_argument("--timeout", type=float, default=rc.TIMEOUT_SECONDS)
    p.add_argument("--generations", type=Path, default=GENERATIONS_DIR)
    p.add_argument("--out", type=Path, default=RESULTS_DIR)
    args = p.parse_args(argv)

    run_dir = args.generations / args.run
    files = generation_files(run_dir)
    if not files:
        raise SystemExit(f"нет файлов генераций в {run_dir}")
    sample = {i["name"]: i for i in json.loads(SAMPLE_FILE.read_text(encoding="utf-8"))["instances"]}
    instances: dict[str, dict] = {}

    def instance_of(name: str) -> dict:
        if name not in instances:
            info = sample[name]
            instances[name] = parse_sm_file(PSPLIB_INSTANCES / info["set"] / f"{name}.sm")
        return instances[name]

    runs = []
    for i, path in enumerate(files, 1):
        rec = json.loads(path.read_text(encoding="utf-8"))
        row = run_generation(rec, sample[rec["instance"]], instance_of(rec["instance"]), args.timeout)
        runs.append(row)
        rpd_text = f", RPD {row['rpd_bks']:.2f}%" if row["rpd_bks"] is not None else ""
        print(f"  [{i}/{len(files)}] {path.name}: {row['status']}{rpd_text}")
    baselines = [b for name in sorted(instances) for b in run_baselines(sample[name], instances[name])]

    out_dir = args.out / args.run
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(out_dir / "runs.csv", runs, RUN_COLUMNS)
    _write_csv(out_dir / "baselines.csv", baselines, BASELINE_COLUMNS)
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8")) \
        if (run_dir / "manifest.json").exists() else {}
    summary = {"run": args.run, "created": datetime.now().isoformat(timespec="seconds"),
               "generation_config": manifest.get("config"), "timeout_s": args.timeout,
               "instances": len(instances), "generations": len(runs), **summarize(runs, baselines)}
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                                          encoding="utf-8")
    for level, s in summary["levels"].items():
        arpd = f"{s['arpd']:.2f}%" if s["arpd"] is not None else "—"
        print(f"Уровень {level}: допустимых {s['valid']}/{s['runs']}, ARPD {arpd}, "
              f"статусы {s['statuses']}, читают meta.indicators: {s['uses_indicators']}")
    for rule, s in summary["rules"].items():
        print(f"Правило {rule}: ARPD {s['arpd']:.2f}% ({s['valid']}/{s['runs']})")
    print(f"Результаты: {out_dir}")
    return summary


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
