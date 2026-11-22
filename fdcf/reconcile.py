"""Three-level reconciliation and the go-live gate.

Level 1 (records)  - completeness and amount integrity of every document
Level 2 (balances) - account activity and cumulative balances by period
Level 3 (reports)  - the reports people rely on: statement of activities,
                     statement of net position, grant and cost-center reports

Each check compares the EXPECTED target (the legacy ledger after the documented
scope rules and account mapping) with the ACTUAL target as read back from the
new system, and fails when any compared cell differs by more than the
tolerance pre-registered for it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import yaml

from .ledger import ACCOUNT_MAP, NEW_ACCOUNT_CLASS, REPORT_LINES, map_accounts

DEFAULT_REGISTRY = Path(__file__).resolve().parent.parent / "config" / "acceptance_registry.yaml"


@dataclass
class CheckResult:
    item_id: str
    level: int
    name: str
    owner: str
    passed: bool
    n_diffs: int
    max_abs_diff: float
    details: pd.DataFrame = field(default_factory=pd.DataFrame)
    waived: int = 0

    @property
    def status(self) -> str:
        if self.passed:
            return "PASS" if not self.waived else "PASS (approved exceptions)"
        return "FAIL"


def load_registry(path: str | Path | None = None) -> dict:
    with open(path or DEFAULT_REGISTRY, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


# ------------------------------------------------------------------ helpers
def _compare(exp: pd.Series, act: pd.Series, tol: float) -> pd.DataFrame:
    df = pd.concat([exp.rename("expected"), act.rename("actual")], axis=1).fillna(0.0)
    df["difference"] = (df["actual"] - df["expected"]).round(2)
    bad = df[df["difference"].abs() > tol + 1e-9]
    return bad.sort_values("difference", key=lambda s: s.abs(), ascending=False)


def _gross(df: pd.DataFrame, by) -> pd.Series:
    return df[df["amount"] > 0].groupby(by)["amount"].sum().round(2)


def _with_class(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["class"] = out["account"].map(NEW_ACCOUNT_CLASS).fillna("unmapped")
    out["report_line"] = out["account"].map(REPORT_LINES).fillna("Unmapped account " + out["account"])
    return out


def _cumulative(s: pd.Series) -> pd.Series:
    # s indexed by (key, period) -> cumulative over periods 1..12 for every key
    keys = s.index.get_level_values(0).unique()
    full = pd.MultiIndex.from_product([keys, range(1, 13)], names=s.index.names)
    return s.reindex(full, fill_value=0.0).groupby(level=0).cumsum().round(2)


# ------------------------------------------------------------------- checks
def _doc_completeness(exp, act, tol):
    src = exp.groupby("xref")["doc_id"].nunique()
    tgt = act.groupby("xref")["doc_id"].nunique()
    df = pd.concat([src.rename("expected"), tgt.rename("actual")], axis=1).fillna(0).astype(int)
    df["difference"] = df["actual"] - df["expected"]
    return df[df["difference"].abs() > tol]


def _doc_amounts(exp, act, tol):
    return _compare(_gross(exp, "xref"), _gross(act, "xref"), tol)


def _doc_balanced(exp, act, tol):
    net = act.groupby("doc_id")["amount"].sum().round(2)
    bad = net[net.abs() > tol]
    return pd.DataFrame({"expected": 0.0, "actual": bad, "difference": bad})


def _control_totals(exp, act, tol):
    e = pd.Series({"debits": exp.loc[exp.amount > 0, "amount"].sum(),
                   "credits": exp.loc[exp.amount < 0, "amount"].sum()}).round(2)
    a = pd.Series({"debits": act.loc[act.amount > 0, "amount"].sum(),
                   "credits": act.loc[act.amount < 0, "amount"].sum()}).round(2)
    return _compare(e, a, tol)


def _tb_activity(exp, act, tol):
    k = ["account", "period"]
    return _compare(exp.groupby(k)["amount"].sum(), act.groupby(k)["amount"].sum(), tol)


def _tb_cumulative(exp, act, tol):
    k = ["account", "period"]
    return _compare(_cumulative(exp.groupby(k)["amount"].sum()),
                    _cumulative(act.groupby(k)["amount"].sum()), tol)


def _report_activities(exp, act, tol):
    e, a = _with_class(exp), _with_class(act)
    sel = lambda d: d[d["class"].isin(["revenue", "expense", "unmapped"])]  # noqa: E731
    k = ["report_line", "period"]
    return _compare(sel(e).groupby(k)["amount"].sum(), sel(a).groupby(k)["amount"].sum(), tol)


def _report_position(exp, act, tol):
    e, a = _with_class(exp), _with_class(act)
    sel = lambda d: d[d["class"].isin(["asset", "liability", "equity", "unmapped"])]  # noqa: E731
    k = ["report_line", "period"]
    return _compare(_cumulative(sel(e).groupby(k)["amount"].sum()),
                    _cumulative(sel(a).groupby(k)["amount"].sum()), tol)


def _report_grant(exp, act, tol):
    e, a = _with_class(exp), _with_class(act)
    sel = lambda d: d[(d["class"] == "expense") & (d["fund"] == "F200")]  # noqa: E731
    k = ["grant", "period"]
    e2 = sel(e).assign(grant=lambda d: d["grant"].replace("", "(no grant)"))
    a2 = sel(a).assign(grant=lambda d: d["grant"].replace("", "(no grant)"))
    return _compare(e2.groupby(k)["amount"].sum(), a2.groupby(k)["amount"].sum(), tol)


def _report_cost_center(exp, act, tol):
    e, a = _with_class(exp), _with_class(act)
    sel = lambda d: d[d["class"] == "expense"].assign(  # noqa: E731
        cost_center=lambda x: x["cost_center"].replace("", "(none)"))
    k = ["cost_center", "period"]
    return _compare(sel(e).groupby(k)["amount"].sum(), sel(a).groupby(k)["amount"].sum(), tol)


CHECKS = {
    "doc_completeness": _doc_completeness, "doc_amounts": _doc_amounts,
    "doc_balanced": _doc_balanced, "control_totals": _control_totals,
    "tb_activity": _tb_activity, "tb_cumulative": _tb_cumulative,
    "report_activities": _report_activities, "report_position": _report_position,
    "report_grant": _report_grant, "report_cost_center": _report_cost_center,
}


def expected_target(source: pd.DataFrame, exclusions: list[str] | None = None,
                    mapping: dict[str, str] | None = None) -> pd.DataFrame:
    """Legacy ledger after documented scope exclusions and the approved account mapping."""
    src = source[~source["doc_id"].isin(exclusions or [])]
    return map_accounts(src, mapping or ACCOUNT_MAP)


def reconcile(source: pd.DataFrame, target: pd.DataFrame, registry: dict | None = None,
              exclusions: list[str] | None = None, approved_exceptions: list[dict] | None = None,
              levels: tuple[int, ...] = (1, 2, 3)) -> list[CheckResult]:
    registry = registry or load_registry()
    exp = expected_target(source, exclusions)
    results = []
    for item in registry["items"]:
        if item["level"] not in levels:
            continue
        tol = float(item.get("tolerance_abs", 0))
        bad = CHECKS[item["check"]](exp, target, tol)
        waived = 0
        for ex in approved_exceptions or []:
            if ex["item"] == item["id"]:
                keys = [str(k) for k in bad.index]
                hit = [k for k in keys if k == str(ex["key"])]
                waived += len(hit)
                bad = bad[[str(k) not in hit for k in bad.index]]
        results.append(CheckResult(
            item_id=item["id"], level=item["level"], name=item["name"], owner=item.get("owner", ""),
            passed=bad.empty, n_diffs=len(bad),
            max_abs_diff=float(bad["difference"].abs().max()) if len(bad) else 0.0,
            details=bad.head(25), waived=waived))
    return results


# ---------------------------------------------------------------- baselines
def baseline_checks(source: pd.DataFrame, target: pd.DataFrame,
                    exclusions: list[str] | None = None) -> dict[str, bool]:
    """Conventional load checks, scope-adjusted. True = the check raised an alarm."""
    exp = expected_target(source, exclusions)
    totals = _control_totals(exp, target, 0.01)
    return {
        "B1_line_count_totals": (len(exp) != len(target)) or not totals.empty,
        "B2_doc_count_totals": (exp["doc_id"].nunique() != target["doc_id"].nunique()) or not totals.empty,
    }


# --------------------------------------------------------------------- gate
def go_live_gate(results: list[CheckResult]) -> str:
    return "GO" if all(r.passed for r in results) else "NO-GO"


def gate_report_markdown(results: list[CheckResult], title: str = "Go-live gate report") -> str:
    decision = go_live_gate(results)
    lines = [f"# {title}", "", f"**Decision: {decision}**", "",
             "| Item | Level | Acceptance criterion | Owner | Status | Cells over tolerance | Largest difference |",
             "|---|---|---|---|---|---|---|"]
    for r in results:
        lines.append(f"| {r.item_id} | {r.level} | {r.name} | {r.owner} | {r.status} | {r.n_diffs} | "
                     f"{r.max_abs_diff:,.2f} |")
    for r in results:
        if not r.passed:
            lines += ["", f"## {r.item_id} — largest differences", "",
                      r.details.reset_index().to_markdown(index=False, floatfmt=",.2f")]
    return "\n".join(lines) + "\n"
