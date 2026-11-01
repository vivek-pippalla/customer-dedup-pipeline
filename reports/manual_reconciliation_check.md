# Reconciliation report

## Latest run

- Run ID: `run_20261031T142259Z_f24a`
- Status: **success**
- Started: 2026-10-31T14:22:59Z
- Ended: 2026-10-31T14:23:02Z
- Input files: ["data/generated/dev_seed1.csv"]
- Error: -

| Count | Value |
|---|---:|
| input_rows | 5000 |
| rejected_rows | 700 |
| valid_rows | 4300 |
| new_version_rows | 0 |
| duplicate_event_rows | 4300 |
| unique_source_records | 4062 |
| golden_records | 3259 |
| merged_away | 803 |
| records_in_merged_clusters | 1475 |
| review_pending | 6826 |
| records_in_pending_review | 1318 |

## Reconciliation identities

| Identity | Left side | Right side | Pass |
|---|---:|---:|:---:|
| Batch: input = rejected + valid | 5000 | 5000 | yes |
| Database: unique = golden + merged away | 4062 | 4062 | yes |
| Database: sum member_count = unique | 4062 | 4062 | yes |
| Aggregate: merged records - merged away = multi-member golden records | 672 | 672 | yes |
| Rejects by reason sum = persisted rejects | 700 | 700 | yes |
| Golden member rows = unique source records | 4062 | 4062 | yes |
| Lineage source membership orphans | 0 | 0 | yes |
| Foreign-key violations | 0 | 0 | yes |

## Rejects by reason

| Reason | Rows |
|---|---:|
| duplicate_key | 100 |
| future_timestamp | 100 |
| invalid_email | 100 |
| invalid_source_system | 100 |
| invalid_timestamp | 100 |
| malformed_row | 100 |
| missing_required | 100 |

## Largest clusters

| Golden ID | Name | Members |
|---|---|---:|
| g_00b07b3128850f94 | Rahul Das | 3 |
| g_02456ff7167bb676 | Arjun Bell | 3 |
| g_065a0e3085b0b50f | Vikram Taylor | 3 |
| g_0b1ac0c624705d74 | Fatima Taylor | 3 |
| g_0b98412dd2088515 | Priya Garcia | 3 |
| g_0fd51923b84cc579 | Arjun Anderson | 3 |
| g_18209f8f6003cd6e | Andrew Kapoor | 3 |
| g_196a65585720b9de | Ward, Rahul | 3 |
| g_1c1a8d71a42440dd | Lucas Foster | 3 |
| g_1c494a89c9a5e2b3 | Reed, Johnny | 3 |

## Review queue by reason

Total: **6826**

| Reason | Pairs |
|---|---:|
| dob_conflict | 4999 |
| name_only | 12 |
| score_below_auto | 9 |
| shared_identifier_conflict | 1314 |
| shared_identifier_only | 492 |

## Capped blocks

No blocks exceeded the configured cap.

## Data quality

Clean rows: **4300**
Phone invalid in latest run: **0**

| Field | Nulls | Null rate |
|---|---:|---:|
| email_norm | 434 | 10.09% |
| phone_norm | 406 | 9.44% |
| name_norm | 0 | 0.00% |
| first_name_canon | 0 | 0.00% |
| last_name_norm | 0 | 0.00% |
| address_norm | 404 | 9.40% |
| postcode_norm | 357 | 8.30% |
| updated_at_utc | 0 | 0.00% |
| dob_norm | 518 | 12.05% |
| soundex_last | 122 | 2.84% |

### Warnings

None recorded.
