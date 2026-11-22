# Financial Data Continuity Framework (FDCF)

**An open method and toolkit for proving that financial records stay accurate when an organization moves to a new ERP system.**

When an organization replaces its financial system, teams usually test whether the data *loads*. FDCF tests whether the figures people rely on are *unchanged*: every record, every account balance, and every report, for every period, against tolerances agreed before any data moves. It then keeps checking through the first financial closes, and packages the evidence as a provenance record for analytics and AI tools that will use the migrated data.

The toolkit is vendor-neutral. It ships with two reference migration paths:

| Path | Legacy tables | Target tables |
|---|---|---|
| `sap` | SAP ECC `BKPF` + `BSEG` | SAP S/4HANA Universal Journal `ACDOCA` |
| `peoplesoft` | PeopleSoft `PS_JRNL_HEADER` + `PS_JRNL_LN` | Generic cloud ERP journal import (segmented account string) |

Table and field names follow each product's public field names, simplified to the fields the framework needs. No vendor code or customer data is included; all data is synthetic.

## The framework in four parts

1. **Acceptance registry (before migration).** A YAML file listing every check that must pass, its owner, and its numeric tolerance ([`config/acceptance_registry.yaml`](config/acceptance_registry.yaml)).
2. **Three-level go-live gate.** The expected target (legacy data after documented scope rules and the approved account mapping) is compared with the target as read back from the new system:
   - **Level 1, records:** every in-scope document loaded exactly once, with the same amounts, balanced.
   - **Level 2, balances:** account activity and cumulative balances for every account and period.
   - **Level 3, reports:** statement of activities, statement of net position, grant expenditure and cost-center reports.

   The decision is **GO** only when every item passes or carries an approved exception.
3. **Hypercare through the first closes.** Close metrics (for example, manual journal entries) are tracked on XmR control charts with limits set from the legacy system's own closes. Hypercare ends when written exit criteria are met.
4. **Lineage and AI-readiness record.** A field-level lineage map plus a JSON record with file hashes, scope exclusions, a completeness profile and the reconciliation results. It is meant to travel with the migrated data into analytics or AI use.

## Quick start

```bash
git clone https://github.com/Elizabethumah-labs/financial-data-continuity.git
cd financial-data-continuity
python -m pip install -r requirements.txt

# One migration end to end: writes legacy and target tables, the gate report,
# the lineage map, the AI-readiness record and an example control chart
python -m fdcf demo --path sap --scenario clean --out out/sap_clean
python -m fdcf demo --path peoplesoft --scenario grant_swap --out out/ps_grant_swap

# The seeded-error validation study (about 8 minutes for 100 trials)
python -m fdcf study --trials 100 --out results

# Tests
python -m pytest -q
```

Scenarios: benign `clean`, `merge_lines`, `exclude_reversals`; defects `drop_document`, `drop_line`, `duplicate_document`, `sign_flip_document`, `scale_error`, `transposition`, `truncation`, `account_mismap`, `period_shift`, `grant_blanked`, `grant_swap`, `cost_center_blanked`.

## Using it on real data

1. Export the legacy and target journal tables to CSV.
2. Write an adapter that reads them into the canonical model (see `fdcf/adapters.py`; each adapter is about 20 lines).
3. Copy and edit the acceptance registry: set tolerances and owners with your controller and auditors *before* the migration.
4. Call `fdcf.reconcile.reconcile(...)` and publish `gate_report_markdown(...)` with your go-live decision.

## Seeded-error study

The study generates synthetic ledgers, runs each one through both migration paths under 12 seeded defect types and 3 benign changes, and compares FDCF with two conventional load checks (record count plus control totals). Results are in [`results/summary.md`](results/summary.md). Because defects are seeded into synthetic data, the study shows **which kinds of error each level of testing can and cannot see**. It is not a measure of field performance.

## Repository layout

```
fdcf/            the toolkit (ledger, adapters, migrate, reconcile, hypercare, lineage, study)
config/          acceptance registry and account mapping
examples/        sample outputs from `fdcf demo`
results/         seeded-error study outputs
tests/           pytest suite
```

## Citing

See [`CITATION.cff`](CITATION.cff). A methodology preprint accompanies this release.

## License

MIT. See [`LICENSE`](LICENSE).
