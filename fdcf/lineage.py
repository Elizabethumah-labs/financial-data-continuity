"""Lineage map and AI-readiness record.

The migration already produces the evidence an AI data-provenance record needs:
where each field came from, every transformation applied, what was excluded and
why, and whether the reconciled figures agree. This module packages that
evidence as a machine-readable record (in the spirit of "datasheets for
datasets") to accompany migrated financial data used by analytics or AI tools.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

import pandas as pd

from .ledger import ACCOUNT_MAP, CANONICAL_COLUMNS

FIELD_LINEAGE = {
    "sap": [
        ("BKPF.BUKRS", "ACDOCA.RBUKRS", "copied"),
        ("BKPF.BELNR", "ACDOCA.BELNR", "renumbered; legacy number kept in ACDOCA.AWREF"),
        ("BKPF.GJAHR", "ACDOCA.GJAHR", "copied"),
        ("BKPF.MONAT", "ACDOCA.POPER", "copied, zero-padded to 3 digits"),
        ("BKPF.BUDAT", "ACDOCA.BUDAT", "copied"),
        ("BSEG.BUZEI", "ACDOCA.DOCLN", "zero-padded to 6 digits"),
        ("BSEG.HKONT", "ACDOCA.RACCT", "account mapping table (config/account_mapping.csv)"),
        ("BSEG.KOSTL", "ACDOCA.RCNTR", "copied"),
        ("BSEG.GEBER", "ACDOCA.RFUND", "copied"),
        ("BSEG.GRANT_NBR", "ACDOCA.RGRANT_NBR", "copied"),
        ("BSEG.SHKZG + BSEG.DMBTR", "ACDOCA.HSL", "signed amount: S = +, H = -"),
        ("BKPF.WAERS", "ACDOCA.RHCUR", "copied"),
    ],
    "peoplesoft": [
        ("PS_JRNL_HEADER.BUSINESS_UNIT", "AccountCombination[segment 1]", "prefix 'BU' removed"),
        ("PS_JRNL_HEADER.JOURNAL_ID", "JournalName", "renumbered; legacy id kept in ReferenceId"),
        ("PS_JRNL_HEADER.JOURNAL_DATE", "AccountingDate", "copied"),
        ("PS_JRNL_HEADER.FISCAL_YEAR + ACCOUNTING_PERIOD", "PeriodName", "formatted YYYY-MM"),
        ("PS_JRNL_LN.JOURNAL_LINE", "LineNumber", "copied"),
        ("PS_JRNL_LN.ACCOUNT", "AccountCombination[segment 2]", "account mapping table"),
        ("PS_JRNL_LN.DEPTID", "AccountCombination[segment 3]", "copied"),
        ("PS_JRNL_LN.FUND_CODE", "AccountCombination[segment 4]", "copied; blank -> 0000"),
        ("PS_JRNL_LN.PROJECT_ID", "AccountCombination[segment 5]", "copied; blank -> 000000"),
        ("PS_JRNL_LN.MONETARY_AMOUNT", "EnteredDr / EnteredCr", "split by sign"),
        ("PS_JRNL_LN.CURRENCY_CD", "CurrencyCode", "copied"),
    ],
}


def lineage_table(path: str) -> pd.DataFrame:
    return pd.DataFrame(FIELD_LINEAGE[path], columns=["source_field", "target_field", "transformation"])


def _sha256(df: pd.DataFrame) -> str:
    return hashlib.sha256(df.to_csv(index=False).encode("utf-8")).hexdigest()


def ai_readiness_record(path_label: str, source_tables: dict, target_tables: dict,
                        target_canonical: pd.DataFrame, results, exclusions: list[str],
                        registry: dict, scope_rule: str | None = None) -> dict:
    expense = target_canonical[target_canonical["account"].str[0] == "5"]
    blank = {c: round(float((target_canonical[c] == "").mean()), 4)
             for c in ["cost_center", "fund", "grant"]}
    return {
        "record_type": "FDCF AI-readiness record",
        "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "migration_path": path_label,
        "dataset": {
            "description": "General-ledger journal lines after migration, read back from the target system",
            "canonical_fields": CANONICAL_COLUMNS,
            "periods_covered": sorted(int(p) for p in target_canonical["period"].unique()),
            "fiscal_years": sorted(int(y) for y in target_canonical["fiscal_year"].unique()),
            "lines": int(len(target_canonical)),
            "documents": int(target_canonical["doc_id"].nunique()),
        },
        "provenance": {
            "source_tables": {k: {"rows": int(len(v)), "sha256": _sha256(v)} for k, v in source_tables.items()},
            "target_tables": {k: {"rows": int(len(v)), "sha256": _sha256(v)} for k, v in target_tables.items()},
            "account_mapping_sha256": hashlib.sha256(json.dumps(ACCOUNT_MAP, sort_keys=True).encode()).hexdigest(),
            "acceptance_registry_version": registry.get("registry_version"),
            "scope_exclusions": {"rule": scope_rule, "documents_excluded": len(exclusions),
                                 "legacy_document_ids": exclusions},
        },
        "completeness_profile": {
            "share_of_lines_with_blank_dimension": blank,
            "expense_lines_in_grant_fund_without_grant": int(
                ((expense["fund"] == "F200") & (expense["grant"] == "")).sum()),
        },
        "reconciliation": {
            "go_live_decision": "GO" if all(r.passed for r in results) else "NO-GO",
            "checks": [{"id": r.item_id, "level": r.level, "criterion": r.name, "status": r.status,
                        "cells_over_tolerance": r.n_diffs, "largest_difference": r.max_abs_diff}
                       for r in results],
        },
        "intended_uses": [
            "financial reporting and analytics on the new system",
            "training or operating forecasting, anomaly-detection and generative-AI tools on ledger history",
        ],
        "known_limitations": [
            "Figures are verified at the levels listed under 'reconciliation' only.",
            "Documents excluded by the scope rule are absent from the target by design.",
        ],
    }
