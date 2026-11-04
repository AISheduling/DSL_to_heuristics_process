from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(HERE))

from make_instances import build, instance_hash  # noqa: E402
from psplib import parse_sm_file  # noqa: E402
from rule_features import FEATURES, rule_features  # noqa: E402
from stats import spearman  # noqa: E402

RESULTS_DIR = HERE / "results"
MANIFEST = HERE / "instances.json"
V1_SAMPLE = ROOT / "experiments" / "v1_pilot" / "sample.json"
PSPLIB_INSTANCES = ROOT / "data" / "psplib" / "instances"

TARGET_RULES = ("LST", "MTS")
DELTA_LABEL = 5.0
TRAIN_SIZES = (30, 60)
TEST_SIZES = (120,)
INDICATORS = ["n", "cnc", "os", "sp", "ad", "la", "i5", "tf", "rf", "ru", "rs", "rc"]
EXPLANATION = {
    "f1": ("В проекте есть работы, которые по поздним стартам выглядят несрочными, но не помещаются "
           "на ресурс рядом с работой критического пути и по сроку окончания срочнее неё. "
           "Правило, выбирающее по позднему старту или по числу преемников, откладывает их, "
           "и проект затягивается; выбор по позднему сроку окончания этого избегает."),
}


def _read(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _write(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def grid_features(run_dir: Path, manifest: dict) -> dict[str, dict]:
    """Признаки проектов сетки; кэш features.csv по хэшу проекта."""
    path = run_dir / "features.csv"
    cached = {r["id"]: r for r in _read(path)} if path.exists() else {}
    out = {}
    for p in manifest["instances"]:
        old = cached.get(p["id"])
        if old and old["hash"] == p["hash"]:
            out[p["id"]] = {k: float(old[k]) for k in FEATURES}
            continue
        inst = build(p)
        if instance_hash(inst) != p["hash"]:
            raise RuntimeError(f"{p['id']}: хэш не совпадает с манифестом — генератор изменился")
        out[p["id"]] = rule_features(inst)
    _write(path, [{"id": i, "hash": p["hash"], **out[i]}
                  for p in manifest["instances"] for i in [p["id"]]])
    return out


def load_grid(run_dir: Path, manifest: dict) -> list[dict]:
    """Строка на проект: параметры, признаки, индикаторы guo2021, проигрыш целевых правил."""
    feats = grid_features(run_dir, manifest)
    gaps: dict[str, dict[str, float]] = {}
    for r in _read(run_dir / "rules.csv"):
        gaps.setdefault(r["id"], {})[r["rule"]] = float(r["gap_vs_others"])
    rows = []
    for p in _read(run_dir / "instances.csv"):
        rows.append({"id": p["id"], "env": p["env"], "n": int(p["n"]), "s": float(p["s"]),
                     **feats[p["id"]], **{f"ind_{k}": float(p[f"ind_{k}"]) for k in INDICATORS},
                     **{f"gap_{r}": gaps[p["id"]][r] for r in TARGET_RULES}})
    return rows


def load_psplib(run_dir: Path, sample_file: Path = V1_SAMPLE) -> list[dict]:
    gaps: dict[str, dict[str, float]] = {}
    for r in _read(run_dir / "psplib_rules.csv"):
        gaps.setdefault(r["instance"], {})[r["rule"]] = float(r["gap_vs_others"])
    rows = []
    for info in json.loads(sample_file.read_text(encoding="utf-8"))["instances"]:
        inst = parse_sm_file(PSPLIB_INSTANCES / info["set"] / f"{info['name']}.sm")
        rows.append({"id": info["name"], "env": "psplib", "n": info["indicators"]["n"],
                     **rule_features(inst), **{f"ind_{k}": float(info["indicators"][k]) for k in INDICATORS},
                     **{f"gap_{r}": gaps[info["name"]][r] for r in TARGET_RULES}})
    return rows


def metrics(pred: list[bool], y: list[bool]) -> dict:
    tp = sum(p and t for p, t in zip(pred, y))
    fp = sum(p and not t for p, t in zip(pred, y))
    fn = sum(not p and t for p, t in zip(pred, y))
    tn = sum(not p and not t for p, t in zip(pred, y))
    tpr = tp / (tp + fn) if tp + fn else None
    tnr = tn / (tn + fp) if tn + fp else None
    rates = [r for r in (tpr, tnr) if r is not None]
    return {"n": len(y), "positives": tp + fn, "fired": tp + fp,
            "precision": tp / (tp + fp) if tp + fp else None, "recall": tpr,
            "specificity": tnr, "balanced_accuracy": mean(rates) if rates else None}


def fit_stump(x: list[float], y: list[bool]) -> dict:
    """Порог с направлением, лучший по сбалансированной точности; ничьи — меньший порог."""
    values = sorted(set(x))
    cuts = [values[0] - 1] + [(a + b) / 2 for a, b in zip(values, values[1:])]
    best = None
    for t in cuts:
        for direction in (">", "<"):
            pred = [(v > t) if direction == ">" else (v < t) for v in x]
            ba = metrics(pred, y)["balanced_accuracy"] or 0.0
            if best is None or ba > best["train_balanced_accuracy"] + 1e-12:
                best = {"threshold": t, "direction": direction, "train_balanced_accuracy": ba}
    return best


def apply(stump: dict, rows: list[dict], feature: str) -> list[bool]:
    t = stump["threshold"]
    return [(r[feature] > t) if stump["direction"] == ">" else (r[feature] < t) for r in rows]


def evaluate_feature(feature: str, rule: str, train: list[dict], tests: dict[str, list[dict]]) -> dict:
    label = lambda rows: [r[f"gap_{rule}"] >= DELTA_LABEL for r in rows]
    stump = fit_stump([r[feature] for r in train], label(train))
    out = {"feature": feature, **stump, "test": {}}
    for name, rows in tests.items():
        out["test"][name] = metrics(apply(stump, rows, feature), label(rows)) if rows else None
    return out


def build_report(run_dir: Path, manifest: dict, psplib: list[dict] | None) -> dict:
    grid = load_grid(run_dir, manifest)
    train = [r for r in grid if r["n"] in TRAIN_SIZES]
    test = [r for r in grid if r["n"] in TEST_SIZES]
    tests = {"n120_isolated": [r for r in test if r["env"] == "isolated"],
             "n120_shared": [r for r in test if r["env"] == "shared"]}
    if psplib:
        tests["psplib"] = psplib
    candidates = list(FEATURES) + [f"ind_{k}" for k in INDICATORS]
    report = {"run": run_dir.name, "delta_label": DELTA_LABEL, "train_sizes": TRAIN_SIZES,
              "test_sizes": TEST_SIZES, "rules": {}}
    for rule in TARGET_RULES:
        results = {f: evaluate_feature(f, rule, train, tests) for f in candidates}
        for f, res in results.items():
            res["spearman_grid"] = spearman([r[f] for r in grid], [r[f"gap_{rule}"] for r in grid])
        # Триггер выбирается только по обучающей выборке; при ничьей — первый по порядку
        best_new = max(FEATURES, key=lambda f: results[f]["train_balanced_accuracy"])
        best_ind = max((f for f in candidates if f.startswith("ind_")),
                       key=lambda f: results[f]["train_balanced_accuracy"])
        report["rules"][rule] = {"features": results, "trigger": best_new, "best_indicator": best_ind,
                                 "explanation_ru": EXPLANATION["f1"]}
    return report


def triggers(report: dict) -> dict:
    """Пороговые правила для маршрутизатора: правило -> признак, порог, объяснение."""
    out = {}
    for rule, r in report["rules"].items():
        f = r["features"][r["trigger"]]
        out[rule] = {"feature": r["trigger"], "direction": f["direction"], "threshold": f["threshold"],
                     "explanation_ru": r["explanation_ru"]}
    return out


def _f(v, fmt="{:.2f}") -> str:
    return "—" if v is None else fmt.format(v)


def to_markdown(rep: dict) -> str:
    lines = [f"# Метахарактеристики F1 — запуск `{rep['run']}`", "",
             f"Метка: правило проиграло, если его makespan хуже лучшего из остальных правил на "
             f"{rep['delta_label']} п. п. и больше. Порог признака подбирается на n ∈ {list(rep['train_sizes'])} "
             f"(оба окружения) по сбалансированной точности, проверяется на n = 120 по окружениям и на PSPLIB.", ""]
    for rule, r in rep["rules"].items():
        lines += [f"## {rule}", "",
                  f"Триггер: `{r['trigger']}`; лучший из индикаторов guo2021: `{r['best_indicator']}`.", "",
                  "| признак | порог | обучение BA | n = 120 isolated BA | n = 120 shared BA | PSPLIB: сработал / проиграл | PSPLIB precision | ρ с проигрышем |",
                  "|---|---|---|---|---|---|---|---|"]
        order = list(FEATURES) + sorted((f for f in r["features"] if f.startswith("ind_")),
                                        key=lambda f: -r["features"][f]["train_balanced_accuracy"])
        for f in order:
            v = r["features"][f]
            iso, sh, ps = v["test"]["n120_isolated"], v["test"]["n120_shared"], v["test"].get("psplib")
            mark = " **(триггер)**" if f == r["trigger"] else (" *(лучший индикатор)*" if f == r["best_indicator"] else "")
            lines.append(f"| `{f}`{mark} | {v['direction']} {v['threshold']:.3g} | {v['train_balanced_accuracy']:.2f} | "
                         f"{_f(iso['balanced_accuracy'])} | {_f(sh['balanced_accuracy'])} | "
                         f"{(str(ps['fired']) + ' / ' + str(ps['positives'])) if ps else '—'} | "
                         f"{_f(ps['precision']) if ps else '—'} | {_f(v['spearman_grid']['rho'])} |")
        lines += ["", f"Объяснение для маршрутизатора: {r['explanation_ru']}", ""]
    lines += ["BA — сбалансированная точность: среднее долей верно угаданных проигрышей и не-проигрышей "
              "(0.5 — как монетка, 1 — без ошибок). ρ — корреляция Спирмена признака с проигрышем по всей сетке.", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> dict:
    parser = argparse.ArgumentParser(description="Подбор порогов метахарактеристик F1 (описание: README.md).")
    parser.add_argument("--run", required=True)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--results-dir", type=Path, default=RESULTS_DIR)
    parser.add_argument("--no-psplib", action="store_true")
    args = parser.parse_args(argv)
    run_dir = args.results_dir / args.run
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    psplib = None if args.no_psplib or not (run_dir / "psplib_rules.csv").exists() else load_psplib(run_dir)
    rep = build_report(run_dir, manifest, psplib)
    (run_dir / "triggers_report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    (run_dir / "triggers.json").write_text(json.dumps(triggers(rep), ensure_ascii=False, indent=1), encoding="utf-8")
    (run_dir / "triggers.md").write_text(to_markdown(rep), encoding="utf-8")
    print(f"-> {run_dir / 'triggers.md'}")
    return rep


if __name__ == "__main__":
    main()
