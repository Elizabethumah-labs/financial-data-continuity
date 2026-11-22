"""Seeded-error validation study.

For each migration path and each random seed:
  1. generate a synthetic legacy ledger and write it in the legacy system's tables;
  2. read it back, migrate it under one scenario (a benign change or one seeded defect);
  3. write the result in the target system's tables and read it back;
  4. run the conventional load checks (baselines) and the three FDCF levels.

Detection rate = share of trials in which a method raised an alarm for a defect.
False-alarm rate = share of trials in which it raised an alarm for a benign change.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from .adapters import PATHS
from .hypercare import signals, simulate_closes, xmr_limits
from .ledger import LedgerSpec, generate_ledger
from .migrate import BENIGN, BENIGN_LABELS, DEFECT_LABELS, DEFECTS, migrate
from .reconcile import baseline_checks, load_registry, reconcile

METHODS = {
    "B1_line_count_totals": "B1: line count + control totals",
    "B2_doc_count_totals": "B2: document count + control totals",
    "L1": "FDCF Level 1 (records)",
    "L1_L2": "FDCF Levels 1-2 (+ balances)",
    "L1_L2_L3": "FDCF Levels 1-3 (+ reports)",
}


def run_trials(trials: int = 50, paths=("sap", "peoplesoft"), docs_per_period: int = 150) -> pd.DataFrame:
    registry = load_registry()
    rows = []
    for path in paths:
        p = PATHS[path]
        to_src, from_src = p["source"]
        to_tgt, from_tgt = p["target"]
        for seed in range(trials):
            legacy = from_src(to_src(generate_ledger(LedgerSpec(seed=seed, docs_per_period=docs_per_period))))
            for scenario in BENIGN + DEFECTS:
                m = migrate(legacy, scenario, seed=seed)
                target = from_tgt(to_tgt(m.target))
                res = reconcile(legacy, target, registry, m.exclusions)
                fail = {r.item_id: (not r.passed) for r in res}
                lvl = {L: any(v for k, v in fail.items() if k.startswith(f"L{L}")) for L in (1, 2, 3)}
                row = {"path": path, "seed": seed, "scenario": scenario,
                       "kind": "benign" if scenario in BENIGN else "defect",
                       **baseline_checks(legacy, target, m.exclusions),
                       "L1": lvl[1], "L1_L2": lvl[1] or lvl[2], "L1_L2_L3": lvl[1] or lvl[2] or lvl[3],
                       "first_level": next((L for L in (1, 2, 3) if lvl[L]), None)}
                row.update({f"item_{k}": v for k, v in fail.items()})
                rows.append(row)
    return pd.DataFrame(rows)


def summarise(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    d = df[df["kind"] == "defect"]
    det = (d.groupby("scenario")[list(METHODS)].mean().mul(100).round(1)
           .reindex(DEFECTS).rename(index=DEFECT_LABELS, columns=METHODS))
    overall = d[list(METHODS)].mean().mul(100).round(1).rename(METHODS)
    det.loc["All defect types (mean)"] = overall
    b = df[df["kind"] == "benign"]
    fa = (b.groupby("scenario")[list(METHODS)].mean().mul(100).round(1)
          .reindex(BENIGN).rename(index=BENIGN_LABELS, columns=METHODS))
    return det, fa


def hypercare_oc(sims: int = 2000, shifts=(0, 0.5, 1, 1.5, 2, 3), seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    out = []
    for s in shifts:
        hit3 = hit6 = 0
        for _ in range(sims):
            base, post = simulate_closes(rng, shift_sigma=s)
            lim = xmr_limits(base)
            sig = [i for i, _ in signals(post, lim)]
            hit6 += bool(sig)
            hit3 += any(i < 3 for i in sig)
        out.append({"shift_in_sigma": s, "signal_within_3_closes_pct": round(100 * hit3 / sims, 1),
                    "signal_within_6_closes_pct": round(100 * hit6 / sims, 1)})
    return pd.DataFrame(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description="FDCF seeded-error validation study")
    ap.add_argument("--trials", type=int, default=50)
    ap.add_argument("--out", default="results")
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    df = run_trials(a.trials)
    df.to_csv(out / "trials.csv", index=False)
    det, fa = summarise(df)
    det.to_csv(out / "detection_rates.csv")
    fa.to_csv(out / "false_alarm_rates.csv")
    oc = hypercare_oc()
    oc.to_csv(out / "hypercare_operating_characteristics.csv", index=False)
    per_path = (df[df.kind == "defect"].groupby("path")[list(METHODS)].mean().mul(100).round(1)
                .rename(columns=METHODS))
    per_path.to_csv(out / "detection_by_path.csv")
    md = ["# FDCF seeded-error study: results", "",
          f"Trials: {a.trials} synthetic ledgers x {df.path.nunique()} migration paths x "
          f"{len(DEFECTS)} defect types and {len(BENIGN)} benign scenarios ({len(df):,} migrations).", "",
          "## Detection rate by defect type (% of trials with an alarm)", "", det.to_markdown(), "",
          "## False-alarm rate on benign changes (% of trials with an alarm)", "", fa.to_markdown(), "",
          "## Detection rate by migration path (all defects)", "", per_path.to_markdown(), "",
          "## Hypercare control chart: chance of a signal after a shift in manual journal entries", "",
          oc.to_markdown(index=False), ""]
    (out / "summary.md").write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
