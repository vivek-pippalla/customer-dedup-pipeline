# Project checklist

Status is based on the implemented behavior and evidence named in the final column. Tests are automated evidence; they do not count as owner-performed manual inspection.

## Required edge cases

| Status | Edge case | Evidence |
|---|---|---|
| [x] DONE | Malformed CSV row is rejected and processing continues | `tests/test_edge_cases.py::test_malformed_csv_is_rejected_and_run_continues` |
| [x] DONE | Missing required field is rejected | `tests/test_validate.py::test_first_reason_codes_and_priority` asserts `missing_required` for an empty required field. |
| [x] DONE | Duplicate key and duplicate event handling is deterministic | `tests/test_validate.py::test_duplicate_key_winner_does_not_depend_on_input_order`; `tests/test_ingest.py::test_insert_versions_is_idempotent_and_counts_conflicts`; `tests/test_ingest.py::test_same_source_record_with_changed_content_inserts_new_version` |
| [x] DONE | Unexpected schema change fails clearly; extra columns are ignored | `tests/test_edge_cases.py::test_schema_mismatch_marks_run_failed_and_extra_columns_warn` |
| [x] DONE | Empty batch leaves outputs unchanged | `tests/test_edge_cases.py::test_zero_byte_batch_succeeds_without_changing_published_outputs`; header-only case also covered by `tests/test_pipeline_e2e.py::test_rerun_is_idempotent_review_decisions_persist_and_empty_leaves_outputs` |
| [x] DONE | Partial publish failure preserves prior output and can be retried | `tests/test_publish.py::test_fault_mid_publish_rolls_back_and_failed_run_is_logged` |
| [x] DONE | Late or out-of-order data does not replace newer values | `tests/test_e2e.py::test_record_in_second_file_with_older_timestamp_does_not_replace_golden_values` |
| [x] DONE | Invalid source system is rejected | `tests/test_validate.py::test_first_reason_codes_and_priority` asserts `invalid_source_system`; sample reject count is in `reports/reconciliation.md`. |
| [x] DONE | Rerunning the same input creates no duplicates | `tests/test_pipeline_e2e.py::test_rerun_is_idempotent_review_decisions_persist_and_empty_leaves_outputs`; sample rerun counts are in `reports/reconciliation.md`. |

## Acceptance criteria

| Status | Criterion | Evidence |
|---|---|---|
| [x] DONE | Keys and referential integrity are checked | `tests/test_db.py::test_foreign_keys_and_status_checks_are_enforced`; SQL query `foreign_key_orphans` in `sql/sample_queries.sql`; `tests/test_publish.py::test_orphan_checks_are_zero_after_publish` |
| [x] DONE | Transforms are deterministic | `tests/test_pipeline_e2e.py::test_shuffled_rows_and_reversed_files_produce_same_golden_tables`; `tests/test_ids.py::test_ids_have_fixed_golden_values` |
| [x] DONE | Counts and aggregates reconcile | SQL query `reconciliation_identities` in `sql/sample_queries.sql`; `reports/reconciliation.md`; publish assertions in `src/dedup/publish.py`. |
| [x] DONE | Invalid records are traceable | `tests/test_ingest.py::test_wrong_column_count_is_structural_reject_and_read_continues`; reject columns are specified in `docs/DATA_DICTIONARY.md`. |
| [x] DONE | Reruns create no duplicates | `tests/test_pipeline_e2e.py::test_rerun_is_idempotent_review_decisions_persist_and_empty_leaves_outputs` |
| [x] DONE | Tests pass | `reports/pytest_output.txt`: saved run is **91 passed in 1.37s on Python 3.11.18**; separate Phase 8C clean-clone run was **91 passed in 1.80s**. |
| [x] DONE | Clean-environment setup works from a clean clone | Phase 8C verified public clone `D:\\PROJECTS\\TESTING_DEDUP\\customer-dedup-pipeline` at `0d8a73e`, fresh Conda `dedup-clean`, Python 3.11.18, both editable installs, six CLI commands, sample results, 91 tests in 1.80s, successful seed-3 2K generate/run/evaluate, and all four sample CSV exports byte-identical to `data/sample/output/` with `fc /b`. |

## Additional verification

These activities supplement the nine edge cases and seven acceptance criteria above.

| Status | Activity | Evidence / result |
|---|---|---|
| [x] DONE | Independently evaluate seed-2 data | Evaluated data/generated/final_seed2_20000.csv against data/generated/final_seed2_20000_truth.csv using the unchanged config/default.toml. Results saved in reports/seed2_evaluation.json: precision 1.0000, recall 0.7235, F1 0.8396, blocking recall 0.9584, zero false auto-merges, and zero false cluster pairs. |
| [x] DONE | Manually inspect 20 review-queue records | Inspected 20 distinct pairs in `out/dev_seed1.db`: 5 `dob_conflict`, 5 `shared_identifier_conflict`, 5 `shared_identifier_only`, 3 `name_only`, and 2 `score_below_auto`. Findings and limitations are recorded in `AI_USAGE.md`. |
| [x] DONE | Trace one golden cluster through lineage by hand | Traced Rahul Das (`g_00b07b3128850f94`) across CRM, WEB, and IMPORT source records. Verified six field-level lineage entries and their survivorship rules. Details are in `AI_USAGE.md`. |
| [x] DONE | Shuffle/reversed-file verification | Independently ran `test_shuffled_rows_and_reversed_files_produce_same_golden_tables`; 1 passed in 0.24 seconds. |
| [x] DONE | Compare reconciliation figures against SQL query results | Generated `reports/manual_reconciliation_check.md` from `out/dev_seed1.db`; all eight reconciliation identities passed. |
| [x] DONE | Review benchmark results and limitations | Reviewed `reports/performance.md` and `reports/seed1_20k_single_run_performance.md`; cross-checked key figures against `README.md`. |
| [x] DONE | Complete personal verification notes | Recorded the completed activities, AI tools, AI assistance, and disclosures in `AI_USAGE.md`. The prompt archive remains explicitly documented as incomplete. |

## Test runs recorded

### Original project environment

- Environment: Project `.venv`
- Python: 3.11.18
- Command:

```cmd
python -m pytest -p no:cacheprovider --basetemp=test-temp
```

- Result: **91 passed in 1.37s**
- Saved console transcript: `reports/pytest_output.txt`

### Clean-clone environment (Phase 8C)

- Clone: `D:\PROJECTS\TESTING_DEDUP\customer-dedup-pipeline`
- Commit: `0d8a73e`
- Environment: Fresh Conda environment `dedup-clean`
- Python: 3.11.18
- Result: **91 passed in 1.80s**
- The exact console output for this run was not saved in the repository.

Automated test evidence does not replace the manual review and lineage activities documented above.