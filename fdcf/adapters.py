"""System adapters: convert between vendor table layouts and the canonical model.

Two migration paths are modelled:

* SAP ECC (BKPF header + BSEG line items)  ->  SAP S/4HANA Universal Journal (ACDOCA)
* PeopleSoft (PS_JRNL_HEADER + PS_JRNL_LN) ->  a generic cloud ERP journal import
  with a segmented account string (Company.Account.CostCenter.Fund.Grant)

The table and field names follow the public field names of each product, but
the layouts are simplified to the fields the framework needs. They are not a
complete reproduction of any vendor's schema.
"""
from __future__ import annotations

import pandas as pd

from .ledger import CANONICAL_COLUMNS


def _canon(df: pd.DataFrame) -> pd.DataFrame:
    out = df[CANONICAL_COLUMNS].copy()
    out["line_no"] = out["line_no"].astype(int)
    out["fiscal_year"] = out["fiscal_year"].astype(int)
    out["period"] = out["period"].astype(int)
    out["amount"] = out["amount"].astype(float).round(2)
    for c in ["doc_id", "xref", "company", "account", "cost_center", "fund", "grant", "currency"]:
        out[c] = out[c].fillna("").astype(str)
    return out.reset_index(drop=True)


# --------------------------------------------------------------------- SAP ECC
def to_sap_ecc(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    hdr = df.drop_duplicates("doc_id")
    bkpf = pd.DataFrame({
        "BUKRS": hdr["company"], "BELNR": hdr["doc_id"].str.zfill(10), "GJAHR": hdr["fiscal_year"],
        "MONAT": hdr["period"], "BUDAT": hdr["posting_date"].str.replace("-", ""),
        "WAERS": hdr["currency"], "XBLNR": hdr["xref"],
    })
    bseg = pd.DataFrame({
        "BUKRS": df["company"], "BELNR": df["doc_id"].str.zfill(10), "GJAHR": df["fiscal_year"],
        "BUZEI": df["line_no"].astype(int).map(lambda n: f"{n:03d}"),
        "HKONT": df["account"].str.zfill(10), "KOSTL": df["cost_center"],
        "GEBER": df["fund"], "GRANT_NBR": df["grant"],
        "SHKZG": (df["amount"] >= 0).map({True: "S", False: "H"}),
        "DMBTR": df["amount"].abs().round(2),
    })
    return {"BKPF": bkpf.reset_index(drop=True), "BSEG": bseg.reset_index(drop=True)}


def from_sap_ecc(t: dict[str, pd.DataFrame]) -> pd.DataFrame:
    m = t["BSEG"].merge(t["BKPF"], on=["BUKRS", "BELNR", "GJAHR"], how="left")
    sign = m["SHKZG"].map({"S": 1, "H": -1})
    out = pd.DataFrame({
        "doc_id": m["BELNR"].str.lstrip("0"), "xref": m["XBLNR"], "line_no": m["BUZEI"].astype(int),
        "company": m["BUKRS"], "fiscal_year": m["GJAHR"], "period": m["MONAT"],
        "posting_date": pd.to_datetime(m["BUDAT"], format="%Y%m%d").dt.strftime("%Y-%m-%d"),
        "account": m["HKONT"].str.lstrip("0"), "cost_center": m["KOSTL"], "fund": m["GEBER"],
        "grant": m["GRANT_NBR"], "amount": sign * m["DMBTR"], "currency": m["WAERS"],
    })
    return _canon(out)


# --------------------------------------------------------- SAP S/4HANA ACDOCA
def to_s4_acdoca(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    acdoca = pd.DataFrame({
        "RLDNR": "0L", "RBUKRS": df["company"], "GJAHR": df["fiscal_year"],
        "BELNR": df["doc_id"].str.zfill(10),
        "DOCLN": df["line_no"].astype(int).map(lambda n: f"{n:06d}"),
        "POPER": df["period"].astype(int).map(lambda p: f"{p:03d}"),
        "BUDAT": df["posting_date"].str.replace("-", ""),
        "RACCT": df["account"].str.zfill(10), "RCNTR": df["cost_center"],
        "RFUND": df["fund"], "RGRANT_NBR": df["grant"],
        "HSL": df["amount"].round(2), "RHCUR": df["currency"], "AWREF": df["xref"],
    })
    return {"ACDOCA": acdoca.reset_index(drop=True)}


def from_s4_acdoca(t: dict[str, pd.DataFrame]) -> pd.DataFrame:
    a = t["ACDOCA"]
    out = pd.DataFrame({
        "doc_id": a["BELNR"].str.lstrip("0"), "xref": a["AWREF"], "line_no": a["DOCLN"].astype(int),
        "company": a["RBUKRS"], "fiscal_year": a["GJAHR"], "period": a["POPER"].astype(int),
        "posting_date": pd.to_datetime(a["BUDAT"], format="%Y%m%d").dt.strftime("%Y-%m-%d"),
        "account": a["RACCT"].str.lstrip("0"), "cost_center": a["RCNTR"], "fund": a["RFUND"],
        "grant": a["RGRANT_NBR"], "amount": a["HSL"], "currency": a["RHCUR"],
    })
    return _canon(out)


# ------------------------------------------------------------------ PeopleSoft
def to_peoplesoft(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    hdr = df.drop_duplicates("doc_id")
    jid = lambda s: "J" + s.str[-9:]  # noqa: E731  JOURNAL_ID is 10 characters
    header = pd.DataFrame({
        "BUSINESS_UNIT": "BU" + hdr["company"], "JOURNAL_ID": jid(hdr["doc_id"]),
        "JOURNAL_DATE": hdr["posting_date"], "FISCAL_YEAR": hdr["fiscal_year"],
        "ACCOUNTING_PERIOD": hdr["period"], "DESCR": "XREF " + hdr["xref"],
    })
    ln = pd.DataFrame({
        "BUSINESS_UNIT": "BU" + df["company"], "JOURNAL_ID": jid(df["doc_id"]),
        "JOURNAL_LINE": df["line_no"].astype(int), "ACCOUNT": df["account"],
        "DEPTID": df["cost_center"], "FUND_CODE": df["fund"], "PROJECT_ID": df["grant"],
        "MONETARY_AMOUNT": df["amount"].round(2), "CURRENCY_CD": df["currency"],
    })
    return {"PS_JRNL_HEADER": header.reset_index(drop=True), "PS_JRNL_LN": ln.reset_index(drop=True)}


def from_peoplesoft(t: dict[str, pd.DataFrame]) -> pd.DataFrame:
    m = t["PS_JRNL_LN"].merge(t["PS_JRNL_HEADER"], on=["BUSINESS_UNIT", "JOURNAL_ID"], how="left")
    out = pd.DataFrame({
        "doc_id": m["JOURNAL_ID"], "xref": m["DESCR"].str.replace("XREF ", "", regex=False),
        "line_no": m["JOURNAL_LINE"], "company": m["BUSINESS_UNIT"].str[2:],
        "fiscal_year": m["FISCAL_YEAR"], "period": m["ACCOUNTING_PERIOD"],
        "posting_date": m["JOURNAL_DATE"], "account": m["ACCOUNT"], "cost_center": m["DEPTID"],
        "fund": m["FUND_CODE"], "grant": m["PROJECT_ID"], "amount": m["MONETARY_AMOUNT"],
        "currency": m["CURRENCY_CD"],
    })
    return _canon(out)


# ------------------------------------------------- Generic cloud ERP journal
def to_cloud_journal(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    combo = (df["company"] + "." + df["account"] + "." + df["cost_center"] + "."
             + df["fund"].replace("", "0000") + "." + df["grant"].replace("", "000000"))
    j = pd.DataFrame({
        "LedgerName": "PRIMARY", "JournalName": "JE-" + df["doc_id"], "ReferenceId": df["xref"],
        "LineNumber": df["line_no"].astype(int), "AccountingDate": df["posting_date"],
        "PeriodName": df["fiscal_year"].astype(str) + "-" + df["period"].astype(int).map(lambda p: f"{p:02d}"),
        "AccountCombination": combo,
        "EnteredDr": df["amount"].clip(lower=0).round(2),
        "EnteredCr": (-df["amount"]).clip(lower=0).round(2),
        "CurrencyCode": df["currency"],
    })
    return {"GL_JOURNAL_IMPORT": j.reset_index(drop=True)}


def from_cloud_journal(t: dict[str, pd.DataFrame]) -> pd.DataFrame:
    j = t["GL_JOURNAL_IMPORT"]
    seg = j["AccountCombination"].str.split(".", expand=True)
    out = pd.DataFrame({
        "doc_id": j["JournalName"].str.replace("JE-", "", regex=False), "xref": j["ReferenceId"],
        "line_no": j["LineNumber"], "company": seg[0],
        "fiscal_year": j["PeriodName"].str[:4].astype(int), "period": j["PeriodName"].str[5:].astype(int),
        "posting_date": j["AccountingDate"], "account": seg[1], "cost_center": seg[2],
        "fund": seg[3].replace("0000", ""), "grant": seg[4].replace("000000", ""),
        "amount": (j["EnteredDr"] - j["EnteredCr"]).round(2), "currency": j["CurrencyCode"],
    })
    return _canon(out)


PATHS = {
    "sap": {"label": "SAP ECC -> SAP S/4HANA",
            "source": (to_sap_ecc, from_sap_ecc), "target": (to_s4_acdoca, from_s4_acdoca)},
    "peoplesoft": {"label": "PeopleSoft -> cloud ERP",
                   "source": (to_peoplesoft, from_peoplesoft), "target": (to_cloud_journal, from_cloud_journal)},
}
