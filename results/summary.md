# FDCF seeded-error study: results

Trials: 100 synthetic ledgers x 2 migration paths x 12 defect types and 3 benign scenarios (3,000 migrations).

## Detection rate by defect type (% of trials with an alarm)

| scenario                                   |   B1: line count + control totals |   B2: document count + control totals |   FDCF Level 1 (records) |   FDCF Levels 1-2 (+ balances) |   FDCF Levels 1-3 (+ reports) |
|:-------------------------------------------|----------------------------------:|--------------------------------------:|-------------------------:|-------------------------------:|------------------------------:|
| Whole document not loaded                  |                               100 |                                   100 |                      100 |                            100 |                           100 |
| One line not loaded                        |                               100 |                                   100 |                      100 |                            100 |                           100 |
| Document loaded twice                      |                               100 |                                   100 |                      100 |                            100 |                           100 |
| Debit/credit reversed on a document        |                                 0 |                                     0 |                        0 |                            100 |                           100 |
| Implied-decimal error (x100) on a document |                               100 |                                   100 |                      100 |                            100 |                           100 |
| Digits transposed on a document            |                               100 |                                   100 |                      100 |                            100 |                           100 |
| Cents truncated on every line              |                               100 |                                   100 |                      100 |                            100 |                           100 |
| Account mapping table error                |                                 0 |                                     0 |                        0 |                            100 |                           100 |
| Period-end cutoff shifted                  |                                 0 |                                     0 |                        0 |                            100 |                           100 |
| Grant code lost on some lines              |                                 0 |                                     0 |                        0 |                              0 |                           100 |
| Two grant codes swapped                    |                                 0 |                                     0 |                        0 |                              0 |                           100 |
| Cost center lost on some lines             |                                 0 |                                     0 |                        0 |                              0 |                           100 |
| All defect types (mean)                    |                                50 |                                    50 |                       50 |                             75 |                           100 |

## False-alarm rate on benign changes (% of trials with an alarm)

| scenario                                         |   B1: line count + control totals |   B2: document count + control totals |   FDCF Level 1 (records) |   FDCF Levels 1-2 (+ balances) |   FDCF Levels 1-3 (+ reports) |
|:-------------------------------------------------|----------------------------------:|--------------------------------------:|-------------------------:|-------------------------------:|------------------------------:|
| No change                                        |                                 0 |                                     0 |                        0 |                              0 |                             0 |
| Lines merged after account consolidation         |                               100 |                                     0 |                        0 |                              0 |                             0 |
| Reversed pairs excluded by documented scope rule |                                 0 |                                     0 |                        0 |                              0 |                             0 |

## Detection rate by migration path (all defects)

| path       |   B1: line count + control totals |   B2: document count + control totals |   FDCF Level 1 (records) |   FDCF Levels 1-2 (+ balances) |   FDCF Levels 1-3 (+ reports) |
|:-----------|----------------------------------:|--------------------------------------:|-------------------------:|-------------------------------:|------------------------------:|
| peoplesoft |                                50 |                                    50 |                       50 |                             75 |                           100 |
| sap        |                                50 |                                    50 |                       50 |                             75 |                           100 |

## Hypercare control chart: chance of a signal after a shift in manual journal entries

|   shift_in_sigma |   signal_within_3_closes_pct |   signal_within_6_closes_pct |
|-----------------:|-----------------------------:|-----------------------------:|
|              0   |                          6.8 |                         14.2 |
|              0.5 |                          9.8 |                         21.6 |
|              1   |                         21.2 |                         45   |
|              1.5 |                         40.6 |                         72.8 |
|              2   |                         58.9 |                         89.4 |
|              3   |                         89.8 |                         99.8 |
