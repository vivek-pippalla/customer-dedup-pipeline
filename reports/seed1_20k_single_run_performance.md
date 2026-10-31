# Single-run performance: seed-1 20K

## Run setup

- Input: existing `data/generated/dev_seed1_20000.csv` (not regenerated)
- Configuration: `config/default.toml` as loaded for the run; no overrides
- Database: fresh SQLite database in a temporary directory, removed after collecting results
- Run ID: `run_20261031T171928Z_cf50`
- Status: `success`
- Measurement: one `run_pipeline` call, wall-clock via `time.perf_counter`; schema setup and temporary-directory creation were outside the timed interval
- No tuning grid, seed-2 run, or production-config edit was performed

## Wall-clock timings

| Stage | Wall time (seconds) | Measurement notes |
|---|---:|---|
| CSV ingestion | Not separately captured | The timing hook did not attach to the pipeline's imported `read_batch` reference. |
| Validation | Not separately captured | The timing hook did not attach to the pipeline's imported `validate_rows` reference. |
| Normalization | 14.567 | Time across calls to `normalize_row` during this run. |
| Blocking | 0.147 | Instrumented `build_blocks` call. |
| Similarity scoring | 0.277 | Instrumented `score_pair` calls. |
| Classification, excluding scoring | 0.115 | Classification wrapper time less the nested scoring time. |
| Clustering | 0.056 | `build_clusters` and `check_clusters`. |
| Survivorship and lineage | 1.035 | `build_golden` calls. |
| Publishing | 1.716 | Instrumented atomic `publish` call. |
| Other / uninstrumented pipeline time | 5.871 | Residual after subtracting the measured exclusive stages above; includes CSV reading, validation, database work, and orchestration. |
| **Total pipeline runtime** | **23.783** | Wall time around the complete `run_pipeline` call. |

The available hooks therefore show normalization as the largest measured component. The 5.871-second residual is substantial and combines the stages whose hooks were missed with other pipeline/database work. This run does not support a precise CSV-ingestion-versus-validation breakdown or a definitive bottleneck comparison across those components.

Peak memory was unavailable: the Windows process-memory sampler did not return a valid measurement during the run. No memory value is inferred.

## Run counts and blocking

| Metric | Measured value |
|---|---:|
| Input rows | 20,000 |
| Valid rows | 17,200 |
| Rejected rows | 2,800 |
| Unique source records | 16,216 |
| Candidate pairs (auto-merge plus review) | 8,038 |
| Naive comparisons | 131,471,220 |
| Blocked comparisons | 14,977 |
| Blocking reduction ratio | 0.9998860815 (99.9886%) |
| Golden records | 12,920 |
| Merged-away records | 3,296 |
| Review queue size | 4,166 |

Rejects by reason: `duplicate_key` 400, `future_timestamp` 400, `invalid_email` 400, `invalid_source_system` 400, `invalid_timestamp` 400, `malformed_row` 400, `missing_required` 400.

## Reconciliation and output checks

The run finished successfully and all recorded reconciliation identities passed:

- Batch identity: 20,000 input rows = 2,800 rejects + 17,200 valid rows.
- Reject identity: 2,800 rejected rows = 2,800 rows counted by reject reason.
- Database identity: 16,216 unique source records = 12,920 golden records + 3,296 merged-away records.
- Golden members: 16,216 rows, matching the unique source-record count.
- Merged-cluster identity: 5,982 member records across multi-member clusters minus 3,296 merged-away records = 2,686 multi-member golden clusters.
- Lineage membership: zero orphan lineage rows.
- Foreign keys: zero violations.

Published table counts were 12,920 `golden_customers`, 16,216 `golden_members`, 77,520 `golden_lineage`, 8,038 `candidate_pairs`, and 4,166 `review_queue` rows. Decision counts were 3,872 `auto_merge`, 4,166 `review`, and 6,939 `non_match`.

## How the run was invoked

The measurement used an inline Python driver from the repository root. It loaded `config/default.toml` with `load_config`, opened a new temporary database, called `init_schema`, then timed exactly one call equivalent to:

```python
run_pipeline(conn, [Path("data/generated/dev_seed1_20000.csv")], config)
```

The driver collected the returned metrics and published table counts, then closed and removed the temporary database. It did not call the evaluator.
