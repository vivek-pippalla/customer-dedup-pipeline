# Reconciliation report

## Latest run

- Run ID: `run_20261031T142328Z_45bc`
- Status: **success**
- Started: 2026-10-31T14:23:28Z
- Ended: 2026-10-31T14:23:28Z
- Input files: ["data/sample/customers_sample.csv"]
- Error: -

| Count | Value |
|---|---:|
| input_rows | 50 |
| rejected_rows | 7 |
| valid_rows | 43 |
| new_version_rows | 0 |
| duplicate_event_rows | 43 |
| unique_source_records | 41 |
| golden_records | 32 |
| merged_away | 9 |
| records_in_merged_clusters | 16 |
| review_pending | 2 |
| records_in_pending_review | 4 |

## Reconciliation identities

| Identity | Left side | Right side | Pass |
|---|---:|---:|:---:|
| Batch: input = rejected + valid | 50 | 50 | yes |
| Database: unique = golden + merged away | 41 | 41 | yes |
| Database: sum member_count = unique | 41 | 41 | yes |
| Aggregate: merged records - merged away = multi-member golden records | 7 | 7 | yes |
| Rejects by reason sum = persisted rejects | 7 | 7 | yes |
| Golden member rows = unique source records | 41 | 41 | yes |
| Lineage source membership orphans | 0 | 0 | yes |
| Foreign-key violations | 0 | 0 | yes |

## Rejects by reason

| Reason | Rows |
|---|---:|
| duplicate_key | 1 |
| future_timestamp | 1 |
| invalid_email | 1 |
| invalid_source_system | 1 |
| invalid_timestamp | 1 |
| malformed_row | 1 |
| missing_required | 1 |

## Largest clusters

| Golden ID | Name | Members |
|---|---|---:|
| g_7ebb9a5f7cc95107 | Ibrahim Reed | 3 |
| g_adb4759950413ddc | Ravi Johnson | 3 |
| g_0453183dd0080e4a | Aisha Carter | 2 |
| g_12ca67b2e36a30b0 | Maggie Das | 2 |
| g_49b649570518e71e | Andrew Price | 2 |
| g_89349679981d8c86 | Maggie Bennett | 2 |
| g_ef1de66cecc93e49 | John Perry | 2 |

## Review queue by reason

Total: **2**

| Reason | Pairs |
|---|---:|
| dob_conflict | 1 |
| shared_identifier_conflict | 1 |

## Capped blocks

No blocks exceeded the configured cap.

## Data quality

Clean rows: **43**
Phone invalid in latest run: **0**

| Field | Nulls | Null rate |
|---|---:|---:|
| email_norm | 5 | 11.63% |
| phone_norm | 7 | 16.28% |
| name_norm | 0 | 0.00% |
| first_name_canon | 0 | 0.00% |
| last_name_norm | 0 | 0.00% |
| address_norm | 6 | 13.95% |
| postcode_norm | 2 | 4.65% |
| updated_at_utc | 0 | 0.00% |
| dob_norm | 3 | 6.98% |
| soundex_last | 0 | 0.00% |

### Warnings

None recorded.
