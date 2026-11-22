"""Command-line entry point.

    python -m fdcf demo  --path sap --scenario clean --out out/
    python -m fdcf study --trials 100 --out results/
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

from . import study
from .adapters import PATHS
from .hypercare import plot_control_chart, simulate_closes
from .ledger import ACCOUNT_MAP, LedgerSpec, generate_ledger
from .lineage import ai_readiness_record, lineage_table
from .migrate import BENIGN, DEFECTS, migrate
from .reconcile import gate_report_markdown, go_live_gate, load_registry, reconcile


def demo(argv):
    ap = argparse.ArgumentParser(prog="fdcf demo", description="Run one migration end to end")
    ap.add_argument("--path", choices=list(PATHS), default="sap")
    ap.add_argument("--scenario", choices=BENIGN + DEFECTS, default="clean")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--registry", default=None, help="acceptance registry YAML")
    ap.add_argument("--out", default="out")
    a = ap.parse_args(argv)

    out = Path(a.out)
    (out / "legacy").mkdir(parents=True, exist_ok=True)
    (out / "target").mkdir(parents=True, exist_ok=True)
    p = PATHS[a.path]
    to_src, from_src = p["source"]
    to_tgt, from_tgt = p["target"]

    legacy_tables = to_src(generate_ledger(LedgerSpec(seed=a.seed)))
    for name, t in legacy_tables.items():
        t.to_csv(out / "legacy" / f"{name}.csv", index=False)
    legacy = from_src(legacy_tables)

    m = migrate(legacy, a.scenario, seed=a.seed)
    target_tables = to_tgt(m.target)
    for name, t in target_tables.items():
        t.to_csv(out / "target" / f"{name}.csv", index=False)
    target = from_tgt(target_tables)

    registry = load_registry(a.registry)
    results = reconcile(legacy, target, registry, m.exclusions)
    (out / "gate_report.md").write_text(
        gate_report_markdown(results, f"Go-live gate report: {p['label']} ({a.scenario})"), encoding="utf-8")
    lineage_table(a.path).to_csv(out / "lineage_map.csv", index=False)
    record = ai_readiness_record(p["label"], legacy_tables, target_tables, target, results, m.exclusions,
                                 registry, "reversed pairs excluded" if m.exclusions else None)
    (out / "ai_readiness_record.json").write_text(json.dumps(record, indent=2), encoding="utf-8")

    base, post = simulate_closes(np.random.default_rng(a.seed), shift_sigma=2.0)
    plot_control_chart(base, post, out / "hypercare_manual_journals.png",
                       title="Manual journal entries per close (example with a 2-sigma shift after go-live)")
    print(f"{p['label']} | scenario: {a.scenario} | decision: {go_live_gate(results)}")
    for r in results:
        print(f"  {r.item_id}  {r.status:<5}  {r.name}")
    print(f"Outputs written to {out.resolve()}")


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("demo", "study"):
        print(__doc__)
        sys.exit(1)
    cmd, rest = sys.argv[1], sys.argv[2:]
    demo(rest) if cmd == "demo" else study.main(rest)


if __name__ == "__main__":
    main()
