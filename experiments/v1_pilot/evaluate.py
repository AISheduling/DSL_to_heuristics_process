from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path
from statistics import mean, quantiles

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from metrics import summarize_rpd  # noqa: E402
from stats import holm, paired_wilcoxon  # noqa: E402

SAMPLE_FILE = HERE / "sample.json"
GENERATIONS_DIR = HERE / "generations"
RESULTS_DIR = HERE / "results"

DELTA_PP = 0.5          # Минимальный интересный эффект, п. п. ARPD (ADR 0003, п. 9)
ALPHA = 0.05
REFERENCE_RULE = "LST"  # Лучшее классическое правило в пилоте и на J30
LEVEL_NAMES = {"a": "(а) LLM с 12 индикаторами", "b": "(б) LLM без метаданных"}
COMPARISONS = [("a", "b"), ("a", REFERENCE_RULE), ("b", REFERENCE_RULE)]


def _num(value: str) -> float | None:
    return float(value) if value not in ("", None) else None


def load_rows(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def level_summary(rows: list[dict]) -> dict:
    ms = [_num(r["makespan"]) if r["status"] == "ok" else None for r in rows]
    by_bks = summarize_rpd(ms, [float(r["bks"]) for r in rows])
    by_cpm = summarize_rpd(ms, [float(r["cpm"]) for r in rows])
    statuses: dict[str, int] = {}
    for r in rows:
        statuses[r["status"]] = statuses.get(r["status"], 0) + 1
    return {"runs": by_bks["runs"], "valid": by_bks["valid"], "share_valid": by_bks["share_valid"],
            "arpd_bks": by_bks["arpd"], "arpd_cpm": by_cpm["arpd"],
            "share_at_bks": by_bks["share_at_reference"], "statuses": statuses}


def per_instance(rows: list[dict], key: str) -> dict[str, dict[str, float]]:
    """{источник: {инстанс: среднее RPD к BKS по допустимым прогонам}}."""
    values: dict[str, dict[str, list[float]]] = {}
    for r in rows:
        if r["status"] != "ok":
            continue
        values.setdefault(r[key], {}).setdefault(r["instance"], []).append(float(r["rpd_bks"]))
    return {src: {inst: mean(v) for inst, v in d.items()} for src, d in values.items()}


def compare(means: dict[str, dict[str, float]]) -> dict:
    raw = {}
    for x, y in COMPARISONS:
        common = sorted(set(means.get(x, {})) & set(means.get(y, {})))
        res = paired_wilcoxon([means[x][i] for i in common], [means[y][i] for i in common])
        raw[f"{x} vs {y}"] = res
    adjusted = holm({k: v["p_value"] for k, v in raw.items()})
    for k, v in raw.items():
        v["p_holm"] = adjusted[k]
        v["significant"] = v["p_holm"] < ALPHA
        v["exceeds_delta"] = v["mean_diff"] is not None and abs(v["mean_diff"]) >= DELTA_PP
    return raw


def breakdown(means: dict[str, dict[str, float]], indicators: dict[str, dict]) -> dict:
    """ARPD источников и разность (а)−(б) по группам RS, OS (терцили) и RF (уровни)."""
    instances = sorted(set(means.get("a", {})) & set(means.get("b", {})))
    out = {}
    for ind in ("rs", "os"):
        values = [indicators[i][ind] for i in instances]
        lo, hi = quantiles(values, n=3) if len(values) >= 3 else (min(values), max(values))
        groups = {f"низкий (≤ {lo:.3f})": lambda v, lo=lo: v <= lo,
                  f"средний ({lo:.3f}; {hi:.3f}]": lambda v, lo=lo, hi=hi: lo < v <= hi,
                  f"высокий (> {hi:.3f})": lambda v, hi=hi: v > hi}
        out[ind] = _group_stats(means, instances, {g: [i for i in instances if f(indicators[i][ind])]
                                                   for g, f in groups.items()})
    rf_levels = sorted({round(indicators[i]["rf"] * 4) / 4 for i in instances})
    out["rf"] = _group_stats(means, instances,
                             {f"{lvl:.2f}": [i for i in instances
                                             if round(indicators[i]["rf"] * 4) / 4 == lvl]
                              for lvl in rf_levels})
    return out


def _group_stats(means, instances, groups: dict[str, list[str]]) -> dict:
    out = {}
    for name, members in groups.items():
        if not members:
            continue
        row = {"n": len(members)}
        for src in ("a", "b", REFERENCE_RULE):
            vals = [means[src][i] for i in members if i in means.get(src, {})]
            row[src] = mean(vals) if vals else None
        diffs = [means["a"][i] - means["b"][i] for i in members]
        row["a_minus_b"] = mean(diffs)
        row["a_better"] = sum(1 for d in diffs if d < 0)
        row["b_better"] = sum(1 for d in diffs if d > 0)
        out[name] = row
    return out


def cost(generation_summary: dict | None, price_in: float | None, price_out: float | None,
         spent_usd: float | None = None) -> dict | None:
    """Оценка по ценам за токены и, если задано, фактическое списание по данным прокси LiteLLM."""
    if not generation_summary:
        return None
    tokens = generation_summary.get("tokens", {})
    out = {"tokens": tokens, "calls": generation_summary.get("tasks")}
    if price_in is not None and price_out is not None:
        usd = tokens.get("prompt", 0) * price_in / 1e6 + tokens.get("completion", 0) * price_out / 1e6
        out.update({"usd": round(usd, 4), "price_in_per_1m": price_in, "price_out_per_1m": price_out,
                    "usd_per_call": round(usd / out["calls"], 5) if out["calls"] else None})
    if spent_usd is not None:
        out.update({"spent_usd": spent_usd,
                    "spent_usd_per_call": round(spent_usd / out["calls"], 5) if out["calls"] else None})
    return out


def build_report(run: str, results_dir: Path, generations_dir: Path, sample_file: Path,
                 price_in: float | None = None, price_out: float | None = None,
                 spent_usd: float | None = None) -> dict:
    runs = load_rows(results_dir / run / "runs.csv")
    baselines = load_rows(results_dir / run / "baselines.csv")
    indicators = {i["name"]: i["indicators"]
                  for i in json.loads(sample_file.read_text(encoding="utf-8"))["instances"]}
    gen_dir = generations_dir / run
    manifest = json.loads((gen_dir / "manifest.json").read_text(encoding="utf-8")) \
        if (gen_dir / "manifest.json").exists() else {}
    gen_summary = json.loads((gen_dir / "summary.json").read_text(encoding="utf-8")) \
        if (gen_dir / "summary.json").exists() else None

    levels = {lvl: level_summary([r for r in runs if r["level"] == lvl])
              for lvl in sorted({r["level"] for r in runs})}
    for lvl in levels:
        levels[lvl]["uses_indicators"] = sum(1 for r in runs if r["level"] == lvl
                                             and r.get("uses_indicators") == "True")
    rules = {rule: level_summary([b for b in baselines if b["rule"] == rule])
             for rule in sorted({b["rule"] for b in baselines})}
    means = {**per_instance(runs, "level"), **per_instance(baselines, "rule")}
    return {
        "run": run, "created": datetime.now().isoformat(timespec="seconds"),
        "generation_config": manifest.get("config"), "generation_commit": manifest.get("git_commit"),
        "instances": len({r["instance"] for r in runs}),
        "generations_per_level": {lvl: s["runs"] for lvl, s in levels.items()},
        "delta_pp": DELTA_PP, "alpha": ALPHA, "reference_rule": REFERENCE_RULE,
        "levels": levels, "rules": rules,
        "comparisons": compare(means),
        "breakdown": breakdown(means, indicators),
        "cost": cost(gen_summary, price_in, price_out, spent_usd),
    }


def _pct(v) -> str:
    if v is None:
        return "—"
    return f"{0.0 if abs(v) < 5e-3 else v:.2f}"   # без «-0.00»


def to_markdown(rep: dict) -> str:
    cfg = rep.get("generation_config") or {}
    lines = [f"# Эксперимент В1: {rep['run']}", "",
             f"Модель `{cfg.get('model')}`, temperature {cfg.get('temperature')}, промпт "
             f"{cfg.get('prompt_version')}, коммит генерации {rep.get('generation_commit')}. "
             f"Инстансов: {rep['instances']}, генераций на уровень: {rep['generations_per_level']}.",
             "", "## Качество", "",
             "| Источник | Допустимых | ARPD к BKS, % | ARPD к CPM, % | Доля = BKS |",
             "|---|---|---|---|---|"]
    for lvl, s in rep["levels"].items():
        lines.append(f"| {LEVEL_NAMES.get(lvl, lvl)} | {s['valid']}/{s['runs']} | {_pct(s['arpd_bks'])} "
                     f"| {_pct(s['arpd_cpm'])} | {_pct((s['share_at_bks'] or 0) * 100)} % |")
    for rule, s in rep["rules"].items():
        lines.append(f"| правило {rule} | {s['valid']}/{s['runs']} | {_pct(s['arpd_bks'])} "
                     f"| {_pct(s['arpd_cpm'])} | {_pct((s['share_at_bks'] or 0) * 100)} % |")
    lines += ["", f"Код уровня (а), читающий `meta.indicators`: {rep['levels'].get('a', {}).get('uses_indicators')} "
              f"из {rep['levels'].get('a', {}).get('runs')}.", "",
              f"## Парные сравнения (по инстансам; δ = {rep['delta_pp']} п. п., α = {rep['alpha']}, Холм)", "",
              "| Сравнение | n | Средняя разность, п. п. | Лучше первый / второй / поровну | p | p (Холм) |",
              "|---|---|---|---|---|---|"]
    for name, c in rep["comparisons"].items():
        lines.append(f"| {name} | {c['n']} | {_pct(c['mean_diff'])} | {c['x_better']} / {c['y_better']} / "
                     f"{c['ties']} | {c['p_value']:.3f} | {c['p_holm']:.3f} |")
    lines += ["", "Разность = первый − второй; отрицательная — первый лучше.", "", "## Разбор по индикаторам", ""]
    titles = {"rs": "RS (сила ресурсов)", "os": "OS (сила упорядоченности)", "rf": "RF (доля ресурсов на работу)"}
    for ind, groups in rep["breakdown"].items():
        lines += [f"### {titles[ind]}", "",
                  f"| Группа | n | (а) | (б) | {rep['reference_rule']} | (а)−(б) | (а) лучше / (б) лучше |",
                  "|---|---|---|---|---|---|---|"]
        for g, r in groups.items():
            lines.append(f"| {g} | {r['n']} | {_pct(r['a'])} | {_pct(r['b'])} | {_pct(r[rep['reference_rule']])} "
                         f"| {_pct(r['a_minus_b'])} | {r['a_better']} / {r['b_better']} |")
        lines.append("")
    c = rep.get("cost")
    if c:
        t = c["tokens"]
        line = (f"## Стоимость\n\nВызовов: {c['calls']}; токены: вход {t.get('prompt')}, выход "
                f"{t.get('completion')} (из них рассуждение {t.get('reasoning')}).")
        if "spent_usd" in c:
            line += f" Списано по данным LiteLLM: ${c['spent_usd']} (${c['spent_usd_per_call']} за вызов)."
        if "usd" in c:
            line += (f" Оценка по ценам ${c['price_in_per_1m']} / ${c['price_out_per_1m']} за 1 млн: "
                     f"${c['usd']} (${c['usd_per_call']} за вызов).")
        lines += [line, ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> dict:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--run", required=True)
    p.add_argument("--price-in", type=float, help="$ за 1 млн входных токенов")
    p.add_argument("--price-out", type=float, help="$ за 1 млн выходных токенов")
    p.add_argument("--spent-usd", type=float, help="фактически списано за запуск (Spend в LiteLLM), $")
    p.add_argument("--results", type=Path, default=RESULTS_DIR)
    p.add_argument("--generations", type=Path, default=GENERATIONS_DIR)
    args = p.parse_args(argv)
    rep = build_report(args.run, args.results, args.generations, SAMPLE_FILE, args.price_in, args.price_out,
                       args.spent_usd)
    out_dir = args.results / args.run
    (out_dir / "report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "report.md").write_text(to_markdown(rep), encoding="utf-8")
    print(to_markdown(rep))
    print(f"Отчет: {out_dir / 'report.md'}")
    return rep


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
