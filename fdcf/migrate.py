"""Simulated migration with documented scope rules, benign changes and seeded defects.

A migration here = legacy canonical ledger -> (scope) -> account mapping ->
renumbering -> optional benign restructuring -> optional seeded defect.

Seeded defects model errors reported in practice: dropped or duplicated
records, mapping-table errors, cutoff errors, lost dimensions and field-format
errors. Each defect returns a ground-truth note so the study can score which
checks detected it.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .ledger import ACCOUNT_MAP, GRANTS, map_accounts

DEFECTS = [
    "drop_document", "drop_line", "duplicate_document", "sign_flip_document",
    "scale_error", "transposition", "truncation", "account_mismap",
    "period_shift", "grant_blanked", "grant_swap", "cost_center_blanked",
]
BENIGN = ["clean", "merge_lines", "exclude_reversals"]

DEFECT_LABELS = {
    "drop_document": "Whole document not loaded",
    "drop_line": "One line not loaded",
    "duplicate_document": "Document loaded twice",
    "sign_flip_document": "Debit/credit reversed on a document",
    "scale_error": "Implied-decimal error (x100) on a document",
    "transposition": "Digits transposed on a document",
    "truncation": "Cents truncated on every line",
    "account_mismap": "Account mapping table error",
    "period_shift": "Period-end cutoff shifted",
    "grant_blanked": "Grant code lost on some lines",
    "grant_swap": "Two grant codes swapped",
    "cost_center_blanked": "Cost center lost on some lines",
}
BENIGN_LABELS = {
    "clean": "No change",
    "merge_lines": "Lines merged after account consolidation",
    "exclude_reversals": "Reversed pairs excluded by documented scope rule",
}

# Plausible wrong mappings: (legacy account, wrong new account)
MISMAPS = [("610000", "6300"), ("420000", "4200"), ("115000", "1200"), ("505000", "5010")]


@dataclass
class MigrationResult:
    target: pd.DataFrame
    exclusions: list[str] = field(default_factory=list)   # legacy doc ids excluded by scope rule
    truth: dict = field(default_factory=dict)


def find_reversal_pairs(df: pd.DataFrame) -> list[tuple[str, str]]:
    """Pairs of documents in the same period whose lines exactly offset."""
    key = (df.assign(k=df["account"] + "|" + df["cost_center"] + "|" + df["fund"] + "|" + df["grant"]
                     + "|" + df["amount"].abs().map(lambda v: f"{v:.2f}"))
             .groupby("doc_id").agg(period=("period", "first"), k=("k", lambda s: tuple(sorted(s))),
                                    net=("amount", lambda s: round(s[s > 0].sum(), 2)),
                                    first=("amount", "first")))
    pairs, used = [], set()
    for _, grp in key.groupby(["period", "k"]):
        if len(grp) < 2:
            continue
        pos = [d for d, r in grp.iterrows() if r["first"] > 0 and d not in used]
        neg = [d for d, r in grp.iterrows() if r["first"] < 0 and d not in used]
        for a, b in zip(sorted(pos), sorted(neg)):
            pairs.append((a, b))
            used.update([a, b])
    return pairs


def _renumber(df: pd.DataFrame, prefix: str) -> pd.DataFrame:
    order = {d: i for i, d in enumerate(dict.fromkeys(df["doc_id"]), start=1)}
    out = df.copy()
    out["doc_id"] = out["doc_id"].map(lambda d: f"{prefix}{order[d]:07d}")
    return out


def _pick_doc(df: pd.DataFrame, rng: np.random.Generator, min_lines: int = 2) -> str:
    sizes = df.groupby("doc_id").size()
    first_doc = df["doc_id"].iloc[0]  # opening-balance document is protected
    cands = sizes[(sizes >= min_lines) & (sizes.index != first_doc)].index
    return str(rng.choice(np.array(cands)))


def seed_defect(df: pd.DataFrame, defect: str, rng: np.random.Generator,
                source: pd.DataFrame | None = None) -> tuple[pd.DataFrame, dict]:
    """Apply one seeded defect to a migrated (new-chart) ledger."""
    out = df.copy()
    truth = {"defect": defect}
    if defect == "drop_document":
        d = _pick_doc(out, rng)
        out = out[out["doc_id"] != d]
        truth["doc"] = d
    elif defect == "drop_line":
        d = _pick_doc(out, rng)
        idx = rng.choice(out.index[out["doc_id"] == d])
        out = out.drop(index=idx)
        truth["doc"] = d
    elif defect == "duplicate_document":
        d = _pick_doc(out, rng)
        dup = out[out["doc_id"] == d].copy()
        dup["doc_id"] = d + "D"
        out = pd.concat([out, dup], ignore_index=True)
        truth["doc"] = d
    elif defect == "sign_flip_document":
        d = _pick_doc(out, rng)
        out.loc[out["doc_id"] == d, "amount"] *= -1
        truth["doc"] = d
    elif defect == "scale_error":
        d = _pick_doc(out, rng)
        out.loc[out["doc_id"] == d, "amount"] = (out.loc[out["doc_id"] == d, "amount"] * 100).round(2)
        truth["doc"] = d
    elif defect == "transposition":
        # two adjacent digits swapped in every line of one document, so it still balances
        # (re-draw until the swap really changes the amounts, so every trial carries a defect)
        for _ in range(50):
            d = _pick_doc(out, rng)
            sel = out["doc_id"] == d
            cents = out.loc[sel, "amount"].abs().mul(100).round().astype(int).astype(str)
            pos = int(rng.integers(0, max(1, cents.str.len().min() - 1)))
            new = cents.map(lambda s: s[:pos] + s[pos + 1] + s[pos] + s[pos + 2:]
                            if len(s) >= pos + 2 else s).astype(int)
            if (new != cents.astype(int)).all():
                break
        out.loc[sel, "amount"] = np.sign(out.loc[sel, "amount"]) * new / 100
        truth.update(doc=d, digit_position=pos)
    elif defect == "truncation":
        out["amount"] = np.trunc(out["amount"])
    elif defect == "account_mismap":
        legacy, wrong = MISMAPS[int(rng.integers(len(MISMAPS)))]
        assert source is not None
        mask = source["account"].to_numpy() == legacy  # rows align: mapping keeps row order
        out.loc[mask, "account"] = wrong
        truth.update(legacy=legacy, wrong=wrong, correct=ACCOUNT_MAP[legacy])
    elif defect == "period_shift":
        p = int(rng.integers(1, 12))
        last = calendar.monthrange(int(out["fiscal_year"].iloc[0]), p)[1]
        day = out["posting_date"].str[8:10].astype(int)
        mask = (out["period"] == p) & (day >= last - 2) & (out["posting_date"].str[8:10] != "01")
        out.loc[mask, "period"] = p + 1
        truth.update(period=p, lines=int(mask.sum()))
    elif defect in ("grant_blanked", "cost_center_blanked"):
        col = "grant" if defect == "grant_blanked" else "cost_center"
        eligible = out.index[out[col] != ""]
        n = max(1, int(len(eligible) * 0.02))
        idx = rng.choice(eligible, size=n, replace=False)
        out.loc[idx, col] = ""
        truth["lines"] = int(n)
    elif defect == "grant_swap":
        a, b = rng.choice(GRANTS, size=2, replace=False)
        ga, gb = out["grant"] == a, out["grant"] == b
        out.loc[ga, "grant"], out.loc[gb, "grant"] = b, a
        truth.update(grants=[str(a), str(b)])
    else:
        raise ValueError(f"Unknown defect {defect}")
    out["amount"] = out["amount"].round(2)
    return out.reset_index(drop=True), truth


def merge_lines(df: pd.DataFrame) -> pd.DataFrame:
    """Benign: combine lines that became identical after the chart-of-accounts merge."""
    keys = ["doc_id", "xref", "company", "fiscal_year", "period", "posting_date",
            "account", "cost_center", "fund", "grant", "currency"]
    sign = np.sign(df["amount"]).astype(int).rename("_sign")
    g = (df.assign(_sign=sign).groupby(keys + ["_sign"], sort=False, as_index=False)["amount"].sum())
    g["line_no"] = g.groupby("doc_id").cumcount() + 1
    g["amount"] = g["amount"].round(2)
    return g.drop(columns="_sign")[df.columns]


def migrate(source: pd.DataFrame, scenario: str = "clean", seed: int = 0,
            doc_prefix: str = "49") -> MigrationResult:
    """Run the simulated migration for one scenario (a benign change or a defect)."""
    rng = np.random.default_rng(seed + 10_000)
    exclusions: list[str] = []
    src = source
    if scenario == "exclude_reversals":
        pairs = find_reversal_pairs(source)
        exclusions = sorted([d for p in pairs for d in p])
        src = source[~source["doc_id"].isin(exclusions)].reset_index(drop=True)
    mapped = map_accounts(src)
    truth: dict = {"scenario": scenario}
    if scenario == "account_mismap":
        mapped, t = seed_defect(mapped, scenario, rng, source=src)
        truth.update(t)
    target = _renumber(mapped, doc_prefix)
    if scenario == "merge_lines":
        target = merge_lines(target)
    if scenario in DEFECTS and scenario != "account_mismap":
        target, t = seed_defect(target, scenario, rng)
        truth.update(t)
    return MigrationResult(target=target.reset_index(drop=True), exclusions=exclusions, truth=truth)
