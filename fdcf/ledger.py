"""Synthetic general ledger in the canonical FDCF format.

Every system adapter reads and writes this one shape, so each check in the
framework is written once and works for any ERP.

Canonical journal-line columns
------------------------------
doc_id        document (journal) identifier in the system that holds the data
xref          identifier of the originating legacy document (lineage key)
line_no       line number inside the document
company       company code / business unit
fiscal_year   fiscal year
period        fiscal period 1-12
posting_date  ISO date (YYYY-MM-DD)
account       general-ledger account
cost_center   cost center / department
fund          fund code ("" when not used)
grant         grant / sponsored project ("" when not used)
amount        signed amount, debit positive, credit negative
currency      ISO currency code
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass

import numpy as np
import pandas as pd

CANONICAL_COLUMNS = [
    "doc_id", "xref", "line_no", "company", "fiscal_year", "period",
    "posting_date", "account", "cost_center", "fund", "grant", "amount", "currency",
]

# Legacy chart of accounts: legacy account -> (name, class)
LEGACY_ACCOUNTS = {
    "100000": ("Cash - operating", "asset"),
    "110000": ("Accounts receivable", "asset"),
    "115000": ("Grants receivable", "asset"),
    "150000": ("Equipment", "asset"),
    "200000": ("Accounts payable", "liability"),
    "210000": ("Accrued payroll", "liability"),
    "300000": ("Net position", "equity"),
    "400000": ("Tuition and fees revenue", "revenue"),
    "410000": ("Grant revenue", "revenue"),
    "420000": ("Other revenue", "revenue"),
    "500000": ("Salaries", "expense"),
    "505000": ("Fringe benefits", "expense"),
    "600000": ("Supplies", "expense"),
    "605000": ("Lab supplies", "expense"),  # merged into 6100 in the new chart
    "610000": ("Travel", "expense"),
    "620000": ("Contractual services", "expense"),
    "630000": ("Depreciation", "expense"),
}

# Account mapping legacy -> new chart (one many-to-one merge, as in real redesigns)
ACCOUNT_MAP = {
    "100000": "1010", "110000": "1200", "115000": "1250", "150000": "1600",
    "200000": "2010", "210000": "2100", "300000": "3000",
    "400000": "4010", "410000": "4200", "420000": "4900",
    "500000": "5010", "505000": "5050",
    "600000": "6100", "605000": "6100",
    "610000": "6200", "620000": "6300", "630000": "6800",
}

NEW_ACCOUNT_CLASS = {
    ACCOUNT_MAP[a]: cls for a, (_, cls) in LEGACY_ACCOUNTS.items()
}

# Report lines used by Level 3 (statement of activities / balance sheet)
REPORT_LINES = {
    "1010": "Cash", "1200": "Receivables", "1250": "Receivables", "1600": "Capital assets",
    "2010": "Payables and accruals", "2100": "Payables and accruals", "3000": "Net position",
    "4010": "Operating revenue", "4200": "Grant revenue", "4900": "Operating revenue",
    "5010": "Personnel", "5050": "Personnel",
    "6100": "Operating expense", "6200": "Operating expense", "6300": "Operating expense",
    "6800": "Depreciation",
}

COST_CENTERS = ["CC100", "CC200", "CC300", "CC400", "CC500", "CC600"]
GRANTS = ["G-NSF-001", "G-NIH-002", "G-DOE-003", "G-NSF-004", "G-DOD-005"]
GRANT_FUND = "F200"   # restricted / sponsored fund
GENERAL_FUND = "F100"


@dataclass
class LedgerSpec:
    company: str = "1000"
    fiscal_year: int = 2026
    docs_per_period: int = 150
    currency: str = "USD"
    seed: int = 0


def _amount(rng: np.random.Generator, scale: float) -> float:
    return round(float(rng.lognormal(mean=np.log(scale), sigma=0.9)), 2)


def _date(rng: np.random.Generator, year: int, period: int) -> str:
    last = calendar.monthrange(year, period)[1]
    day = int(rng.integers(1, last + 1))
    return f"{year:04d}-{period:02d}-{day:02d}"


def generate_ledger(spec: LedgerSpec | None = None) -> pd.DataFrame:
    """Generate one fiscal year of balanced journal entries (legacy chart)."""
    spec = spec or LedgerSpec()
    rng = np.random.default_rng(spec.seed)
    rows: list[dict] = []
    doc_no = 0

    def add(period: int, date: str, lines: list[tuple[str, str, str, str, float]]):
        nonlocal doc_no
        doc_no += 1
        doc_id = f"{spec.fiscal_year}{doc_no:06d}"
        for i, (acct, cc, fund, grant, amt) in enumerate(lines, start=1):
            rows.append({
                "doc_id": doc_id, "xref": doc_id, "line_no": i, "company": spec.company,
                "fiscal_year": spec.fiscal_year, "period": period, "posting_date": date,
                "account": acct, "cost_center": cc, "fund": fund, "grant": grant,
                "amount": round(amt, 2), "currency": spec.currency,
            })

    # Opening balances in period 1
    ob = {"100000": 2_500_000.00, "110000": 640_000.00, "115000": 410_000.00, "150000": 3_900_000.00,
          "200000": -720_000.00, "210000": -380_000.00}
    ob["300000"] = -round(sum(ob.values()), 2)
    add(1, f"{spec.fiscal_year}-01-01",
        [(a, "CC100", GENERAL_FUND, "", v) for a, v in ob.items()])

    for period in range(1, 13):
        for _ in range(spec.docs_per_period):
            date = _date(rng, spec.fiscal_year, period)
            kind = rng.choice(["grant_exp", "op_exp", "revenue", "payment", "receipt", "travel"],
                              p=[0.25, 0.25, 0.15, 0.15, 0.10, 0.10])
            cc = str(rng.choice(COST_CENTERS))
            if kind == "grant_exp":
                g = str(rng.choice(GRANTS))
                acct = str(rng.choice(["600000", "605000", "620000"]))
                amt = _amount(rng, 1800)
                add(period, date, [(acct, cc, GRANT_FUND, g, amt),
                                   ("200000", cc, GRANT_FUND, g, -amt)])
            elif kind == "op_exp":
                if rng.random() < 0.3:  # mixed invoice: supplies + lab supplies on one document
                    a1, a2 = _amount(rng, 800), _amount(rng, 500)
                    add(period, date, [("600000", cc, GENERAL_FUND, "", a1),
                                       ("605000", cc, GENERAL_FUND, "", a2),
                                       ("200000", cc, GENERAL_FUND, "", -(a1 + a2))])
                else:
                    acct = str(rng.choice(["600000", "605000", "620000"]))
                    amt = _amount(rng, 1200)
                    add(period, date, [(acct, cc, GENERAL_FUND, "", amt),
                                       ("200000", cc, GENERAL_FUND, "", -amt)])
            elif kind == "travel":
                g = str(rng.choice(GRANTS + ["", ""]))
                fund = GRANT_FUND if g else GENERAL_FUND
                amt = _amount(rng, 900)
                add(period, date, [("610000", cc, fund, g, amt),
                                   ("200000", cc, fund, g, -amt)])
            elif kind == "revenue":
                acct, ar = (("400000", "110000") if rng.random() < 0.7 else ("420000", "110000"))
                amt = _amount(rng, 6000)
                add(period, date, [(ar, cc, GENERAL_FUND, "", amt),
                                   (acct, cc, GENERAL_FUND, "", -amt)])
            elif kind == "payment":
                amt = _amount(rng, 2500)
                add(period, date, [("200000", cc, GENERAL_FUND, "", amt),
                                   ("100000", cc, GENERAL_FUND, "", -amt)])
            else:  # receipt
                amt = _amount(rng, 4000)
                add(period, date, [("100000", cc, GENERAL_FUND, "", amt),
                                   ("110000", cc, GENERAL_FUND, "", -amt)])
            if kind in ("op_exp", "grant_exp") and rng.random() < 0.03:
                # posted in error and reversed in the same period
                last_doc = rows[-1]["doc_id"]
                prev = [r for r in rows if r["doc_id"] == last_doc]
                add(period, date, [(r["account"], r["cost_center"], r["fund"], r["grant"], -r["amount"])
                                   for r in prev])

        # Month-end payroll: several cost centers and grants, salary + fringe vs accrued payroll
        date = f"{spec.fiscal_year}-{period:02d}-{calendar.monthrange(spec.fiscal_year, period)[1]:02d}"
        lines, total = [], 0.0
        for cc in COST_CENTERS:
            for g in [""] + list(rng.choice(GRANTS, size=2, replace=False)):
                fund = GRANT_FUND if g else GENERAL_FUND
                sal = _amount(rng, 22000)
                fr = round(sal * 0.31, 2)
                lines += [("500000", cc, fund, g, sal), ("505000", cc, fund, g, fr)]
                total += sal + fr
        lines.append(("210000", "CC100", GENERAL_FUND, "", -round(total, 2)))
        add(period, date, lines)
        # Grant revenue recognised on grant expenditure (simplified)
        gr = _amount(rng, 45000)
        add(period, date, [("115000", "CC100", GRANT_FUND, str(rng.choice(GRANTS)), gr),
                           ("410000", "CC100", GRANT_FUND, "", -gr)])
        # Depreciation
        dep = round(3_900_000 / 120, 2)
        add(period, date, [("630000", "CC100", GENERAL_FUND, "", dep),
                           ("150000", "CC100", GENERAL_FUND, "", -dep)])

    df = pd.DataFrame(rows, columns=CANONICAL_COLUMNS)
    # Make every document balance to the cent after rounding
    net = df.groupby("doc_id")["amount"].transform("sum").round(2)
    last = df.groupby("doc_id")["line_no"].transform("max") == df["line_no"]
    df.loc[last, "amount"] = (df.loc[last, "amount"] - net[last]).round(2)
    return df


def map_accounts(df: pd.DataFrame, mapping: dict[str, str] | None = None) -> pd.DataFrame:
    """Translate legacy accounts to the new chart of accounts."""
    mapping = mapping or ACCOUNT_MAP
    out = df.copy()
    missing = set(out["account"]) - set(mapping)
    if missing:
        raise KeyError(f"Accounts with no mapping: {sorted(missing)}")
    out["account"] = out["account"].map(mapping)
    return out
