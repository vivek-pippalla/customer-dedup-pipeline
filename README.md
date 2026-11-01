# Customer deduplication pipeline

This repository implements a deterministic, batch customer-record deduplication pipeline in Python 3.11, SQLite, and RapidFuzz. It ingests CSV files into append-only versioned raw history, validates and normalizes rows, generates blocked candidate pairs, scores and classifies them through evidence gates, clusters only approved auto-merge pairs, selects survivorship values with field-level lineage, and publishes results atomically; the evaluator separately compares published clusters with synthetic ground truth. The recorded benchmark and evaluation results below are specific to generated data and do not establish real-world accuracy.

## Quick start

From the repository root, use either Conda setup path:

```powershell
conda env create -f environment.yml
conda activate dedup
python -m pip install -e .
```

If the `dedup` environment already exists:

```powershell
conda activate dedup
python -m pip install -e .
```

Plain Windows virtual environment alternative:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

For development and tests, install the declared extra with `python -m pip install -e ".[dev]"`. The base `python -m pip install -e .` installation does not install the optional pytest dependency. The package defines a `dedup` command and can also be run as `python -m dedup.cli`.

## Run the sample

The sample CSV is `data/sample/customers_sample.csv`. Commands below use PowerShell-safe quoting and create/update `out/dedup.db`:

```powershell
python -m dedup.cli init-db --db out/dedup.db
python -m dedup.cli run --input data/sample/customers_sample.csv --db out/dedup.db --config config/default.toml --as-of 2026-10-31T00:00:00Z
python -m dedup.cli report --db out/dedup.db --out reports/reconciliation.md --export-dir out/exports
```

The saved sample report records 50 input rows, 7 rejects, 43 valid rows, 41 unique source records, 32 golden records, 9 merged-away records, and 2 pending review pairs. A fresh database had 43 new versions; the later saved rerun report shows 43 duplicate events and no new versions. See [reports/sample_reconciliation.md](reports/sample_reconciliation.md) and [reports/reconciliation.md](reports/reconciliation.md).

## Generate data

The generator emits exactly the requested number of CSV data rows and a separate truth CSV. Defaults are seed 1 and the configured generator rates; specify rates explicitly to make an experiment self-documenting.

```powershell
python -m dedup.cli generate --rows 2000 --seed 3 --out data/generated/dev_seed3_2000.csv --truth-out data/generated/dev_seed3_2000_truth.csv
python -m dedup.cli run --input data/generated/dev_seed3_2000.csv --db out/dedup.db --config config/default.toml --as-of 2026-10-31T00:00:00Z
```

Options include `--dup-rate`, `--family-rate`, `--invalid-rate`, `--late-rate`, and `--batches`. The pipeline `run` command does not accept ground truth; only `evaluate` reads it.

## Evaluate and report

Evaluate the current published database against its matching truth file:

```powershell
python -m dedup.cli evaluate --db out/dedup.db --truth data/generated/dev_seed3_2000_truth.csv
```

`evaluate` prints JSON metrics, including cluster pair precision/recall/F1, auto-merge precision, and blocking/miss breakdowns where available. Produce a Markdown reconciliation report and reproducible CSV table exports with:

```powershell
python -m dedup.cli report --db out/dedup.db --out reports/reconciliation.md --export-dir out/exports
```

The report command writes the requested path; it does not automatically choose a report filename. Generated data and databases are ignored by git under the repository's ignore rules.

## Architecture and flow

```text
CSV file(s)
   |
   v
 INGEST -> VALIDATE -> NORMALIZE --(stage 1 transaction)--> raw versions + rejects + clean rows
                                                               |
                                  whole stored history <-------+
                                                               v
                       BLOCK -> SCORE -> CLASSIFY -> CLUSTER -> SURVIVE
                                  in-memory compute             |
                                                               v
                 PUBLISH (single transaction; replace derived outputs)
                  | golden_customers / golden_members / golden_lineage
                  | candidate_pairs / regenerated review_queue
                  + runs + reconciliation checks
```

### Stages and transactions

1. **Ingest, validate, normalize:** one transaction appends accepted raw versions, rejects, and clean derived rows. Duplicate deliveries are counted without inserting duplicate versions.
2. **Compute:** reads all stored raw and clean history, chooses each source record's current version, then blocks, scores, classifies, clusters, and computes survivors in memory. It writes no database data.
3. **Publish:** replaces golden outputs, candidate pairs, and review queue in one transaction. A failed publish rolls back to the previous published state.
4. **Run log:** run start and completion/failure are recorded outside the publish transaction. An interrupted prior `running` record is marked abandoned on the next start.

## Data model

See the full column-level [data dictionary](docs/DATA_DICTIONARY.md).

| Table | Grain | Key / relationship |
|---|---|---|
| `raw_customer_records` | One distinct delivered content version | `version_id`; belongs to `source_record_id` |
| `clean_customers` | One normalized version | `version_id` -> raw version |
| `rejects` | One rejected input row identity | `reject_id`; unique file/row/raw hash |
| `runs` | One pipeline execution | `run_id` |
| `candidate_pairs` | One canonical source-record pair retained for merge/review | `pair_id`; `a < b` |
| `golden_customers` | One current output cluster | `golden_id` |
| `golden_members` | One source record in one golden cluster | (`golden_id`, `source_record_id`) |
| `golden_lineage` | One selected field per golden cluster | (`golden_id`, `field_name`) |
| `review_queue` | One currently reviewable pair | `pair_id` -> candidate pair |
| `review_decisions` | One persisted human decision per pair | `pair_id`; separate from regenerated queue |

```text
 runs 1----* raw_customer_records 1----1 clean_customers
   |                  |
   |                  +----* golden_members *----1 golden_customers
   |                                      \
   |                                       +----* golden_lineage
   +----* candidate_pairs 1----0..1 review_queue
                         \
                          +----0..1 review_decisions (persisted separately)
```

`golden_members` and `golden_lineage` both identify which source record/version contributed to the output. The queue is rebuilt at publish time; review decisions are kept in their own table.

## Naming and identifiers

- Python variables, functions, database columns, and table names use `snake_case`.
- `source_record_id = sha1(upper(trim(source_system)) + '|' + trim(source_native_id))[:16]` identifies a logical source record.
- `row_hash = sha1(original field values in fixed order joined by '\x1f')[:16]`; `version_id = sha1(source_record_id + '|' + row_hash)[:16]` identifies one distinct content version.
- `golden_id = 'g_' + sha1('|'.join(sorted member source_record_ids))[:16]`; membership changes can change the golden ID.
- `pair_id = sha1(min(a,b) + '|' + max(a,b))[:16]` is based on source-record IDs, so content updates do not change it.
- `run_id` is `run_` plus a UTC compact timestamp and random four-hex suffix; it names an execution and is not part of data IDs.
- Stored normalized timestamps use UTC ISO-8601 form `YYYY-MM-DDTHH:MM:SSZ`. Naive input timestamps are interpreted as UTC.
- Raw/reject provenance includes `source_file` (basename), source row number, and first-seen run ID where applicable.

## Definitions

- **Exact duplicate:** an auto-merged pair with equal normalized email and name, and equal phone when both phones are present. Stored as `match_tier = 'exact'`.
- **Probable duplicate:** an auto-merged pair that does not meet that exact definition. Stored as `match_tier = 'probable'`.
- **Review case:** a plausible pair or a pair caught by a guard; it is never merged automatically.
- **Source record:** one logical customer within one source system, identified by `source_record_id`.
- **Version:** one delivered content state, identified by `version_id`.
- **Current version:** the version with the greatest `updated_at_utc`; ties go to the smallest `row_hash`.

## Matching and evidence gates

Blocking takes the union of pairs sharing normalized email, normalized phone, or Soundex(last name) + first initial + postcode. A key block above `block_cap` (default 200) is skipped and reported with its potential pair count. Candidate scores use RapidFuzz Jaro-Winkler for names, token-set similarity for addresses, and configured weighted features. Missing features are excluded and the remaining weights renormalized; coverage is recorded separately. Score ranks evidence; the gates below decide.

| # | Condition (first applicable row wins) | Decision | Reason |
|---:|---|---|---|
| 1 | DOB conflicts and a strong identifier exists | Review | `dob_conflict` |
| 2 | DOB conflicts and no strong identifier exists | Non-match | `dob_conflict` |
| 3 | Shared email/phone, with different non-initial canonical first names | Review | `shared_identifier_conflict` |
| 4 | Not strong ID and score >= review threshold | Review | `name_only` |
| 5 | Not strong ID | Non-match | `low_score` |
| 6 | Strong ID, compatible names, score >= auto threshold, coverage >= minimum | Auto-merge | `auto_merge` |
| 7 | Strong ID but names incompatible or coverage too low | Review | `shared_identifier_only` |
| 8 | Strong ID and other gates pass, but score below auto threshold | Review | `score_below_auto` |

Strong ID means equal email, equal phone, or equal normalized name plus equal DOB when both are present. Compatible names require equal canonical first names and last-name Jaro-Winkler at least the configured threshold; missing or initial-only names are incompatible. Current defaults are auto `0.90`, review `0.65`, minimum coverage `0.50`, and last-name threshold `0.90`.

Auto-merge edges form clusters with union-find. For clusters of at least three members, all member pairs are checked for DOB and shared-first-name conflicts. A conflicting cluster is split to singletons and its merge pairs demoted to review as `transitive_conflict`.

## Survivorship and lineage

The source priority is configured as CRM (1), WEB (2), IMPORT (3). Every listed final tie-break uses the smallest `source_record_id`.

| Golden field | Winner chain |
|---|---|
| `full_name` | non-nickname first name -> most tokens -> longest -> best source priority -> latest timestamp -> smallest ID |
| `email` | valid values -> best source priority -> latest timestamp -> smallest ID |
| `phone` | valid 10-digit values -> latest timestamp -> best source priority -> smallest ID |
| `address` | most complete components -> latest timestamp -> best priority -> smallest ID |
| `postcode` | address winner's postcode -> best priority -> latest timestamp -> smallest ID |
| `dob` | majority value -> best priority -> smallest ID |

`golden_lineage` stores the selected field value, source record, version, source system, applied rule, and run. If no member supplies a field value, the lineage row has a NULL value and `rule_applied = 'no_value'`. `golden_members` records every member and the version current when the cluster was built.

## Reconciliation identities

The pipeline asserts the identities during publish; the SQL checks are also in [sql/sample_queries.sql](sql/sample_queries.sql). Definitions: `valid_rows = new_version_rows + duplicate_event_rows`; `merged_away = unique_source_records - golden_records`; records pending review remain separate golden records.

1. Batch: `input_rows = rejected_rows + valid_rows`.
2. Database: `unique_source_records = golden_records + merged_away`, and `SUM(member_count) = unique_source_records`.
3. Aggregates: `records_in_merged_clusters - merged_away` equals the number of multi-member golden clusters; rejects by reason sum to rejects; golden member rows equal unique source records; lineage membership orphans and foreign-key violations are zero.

For the saved sample run: `50 = 7 + 43`; `41 = 32 + 9`; `SUM(member_count) = 41`; and `16 merged-cluster members - 9 merged-away = 7 multi-member golden clusters`. The report records zero lineage orphans and zero foreign-key violations. The sample run and these values are recorded in [reports/reconciliation.md](reports/reconciliation.md).

## Operational behaviour

- **Idempotency:** ingesting the same file again inserts no new raw versions and does not duplicate rejects. The full recompute produces the same golden IDs/content for unchanged data; repeated sample-run counts are illustrated in the reports.
- **Retry:** if publish fails, its transaction rolls back, leaving the last successful output and a failed run record. Retry by running the same command again.
- **Restart/crash:** stage 1 commits separately and is idempotent; publish is atomic. On the next run, a leftover `running` row is marked abandoned/failed. There is no partially published set of golden tables.
- **Late data/backfill:** ingesting an older version later preserves it in history, but current-version selection still uses latest `updated_at_utc` (hash tie-break), then recomputes from the complete history.
- **Concurrency:** SQLite is configured for a single writer; concurrent pipeline runs are not supported as an operational guarantee.

## Testing

Run the test suite from the repository root:

```powershell
python -m pytest
```

The tests cover pure transformations and decision rules (IDs, ingest, validation, normalization, blocking, scoring, classification, clustering, survivorship), database constraints and transaction rollback, end-to-end reruns and ordering, fault injection, SQL reconciliation, generator determinism, evaluation, and CLI/package smoke checks. The saved transcript [reports/pytest_output.txt](reports/pytest_output.txt) contains one full-suite run: **91 passed in 1.37s** on Python 3.11.18. The separately verified clean-clone run passed 91 tests in 1.80s; details are below.

## Clean-clone verification

Phase 8C was verified from the public repository cloned to `D:\PROJECTS\TESTING_DEDUP\customer-dedup-pipeline` at commit `0d8a73e`. A fresh Conda environment named `dedup-clean` used Python 3.11.18. Both `python -m pip install -e .` and `python -m pip install -e ".[dev]"` succeeded; the latter installs the optional test dependency. `python -m dedup.cli --help` listed all six commands.

The sample pipeline succeeded with 50 input rows, 7 rejected, 43 valid, 41 unique source records, 32 golden records, 9 merged-away records, and 2 pending review pairs. The four exported CSVs—`golden_customers.csv`, `golden_lineage.csv`, `rejects.csv`, and `review_queue.csv`—matched the committed files in `data/sample/output/` byte-for-byte using `fc /b`.

The clean-clone test command `python -m pytest -p no:cacheprovider --basetemp=test-temp` passed **91 tests in 1.80s**. A separate 2,000-row seed-3 dataset was generated, processed, and evaluated successfully. The exact clean-clone pytest console output was not added to `reports/pytest_output.txt`; that file retains its separately captured 91-pass run shown above.

## Evaluation and performance evidence

All measurements below are copied from saved reports and use synthetic records.

### Seed-1 evaluation comparison

The saved comparison report evaluates 20,000 generated input rows against 5,434 true pairs. Both profiles had cluster precision 100.00%, auto-merge precision 100.00%, and zero false auto-merges. Defaults had cluster recall 71.88% and F1 83.64%; the in-memory name-forward profile had recall 73.48% and F1 84.71%, with 4,056 review pairs versus 4,166. This is one seed's result, not a general accuracy claim. See [reports/seed1_defaults_vs_name_forward.md](reports/seed1_defaults_vs_name_forward.md).

### Blocking experiment and 100,000-row run

The separate 2,000-row seed-3 comparison scored 1,304,920 naive pairs in 21.7041 seconds versus 1,690 blocked candidates in 0.0291 seconds; block generation took 0.0113 seconds. Reduction was 99.8705%, with blocking recall 95.5939% (499 of 522 true pairs found; no capped blocks).

The seed-3 100,000-row pipeline run completed in **450.995 seconds (7 min 30.995 sec)**. It accepted 86,000 rows and rejected 14,000; found 81,092 unique source records, 64,250 golden records, 16,842 merged-away records, 41,601 candidate pairs, and 21,831 review pairs. It measured 218,140 blocked comparisons versus 3,287,915,686 naive comparisons (the latter is arithmetic only), a 99.9934% reduction. Three blocks skipped 2,513,750 potential pairs. Peak Python allocation was 561.0 MiB and sampled process working set was 1.356 GiB. Details and stage timings: [reports/performance.md](reports/performance.md).

The separate one-run seed-1 20K timing report records total runtime 23.783 seconds; ingestion and validation were not separately captured, and process peak memory was unavailable. See [reports/seed1_20k_single_run_performance.md](reports/seed1_20k_single_run_performance.md).

## Assumptions

These correspond to section 15.1 of [docs/BUILD_PLAN.md](docs/BUILD_PLAN.md); details reflect the implementation and configured behavior.

| ID | Working assumption |
|---|---|
| A1 | The entity is customers and available records are synthetic; metrics do not transfer directly to real data. |
| A2 | Email and phone can be shared by families or role accounts; explicit conflict gates and block caps contain, but do not eliminate, that risk. |
| A3 | `(source_system, source_native_id)` identifies one logical record; changed content is a new version. |
| A4 | `updated_at` is business version time; naive values are treated as UTC. |
| A5 | Phone normalization targets Indian ten-digit values after removing a leading `0` or `91`; other lengths become NULL and the row is retained. |
| A6 | Source precedence is CRM, WEB, IMPORT as configured. |
| A7 | A false merge is treated as costlier than a missed duplicate; uncertain cases go to review. |
| A8 | Reject idempotency uses the source filename/basename and assumes basenames are unique for distinct files. |
| A9 | Matching DOBs contribute evidence; conflicting DOBs prevent auto-merge, with strong-ID conflicts sent to review. |
| A10 | Full recomputation is acceptable at the benchmarked 100K-row input size on the reported machine. |
| A11 | SQLite is operated with one writer at a time; concurrent runs are not supported. |
| A12 | Generator entity IDs define truth for evaluation; results measure the generator's noise model. |

## Key decisions and trade-offs

| Decision | Trade-off |
|---|---|
| SQLite and standard library orchestration | Simple local setup and real transactions; one-writer limit. |
| Own matching, gates, clustering, and survivorship; RapidFuzz only for string similarity | Rules remain inspectable; weights and thresholds need domain validation. |
| Evidence gates decide; scores rank | Avoids score-only email/phone merges; more uncertain pairs require review. |
| Append-only versions and full recompute | Deterministic late-data handling; runtime grows with stored history. |
| Hash-derived golden IDs | Repeatable for the same membership; ID changes when membership changes. |
| Keep review decisions apart from regenerated queue | Decisions persist; they are not yet applied to clustering. |
| Block cap | Bounds comparisons; may lose recall, which is counted and reported. |

See [DESIGN_NOTES.md](DESIGN_NOTES.md) for the fuller decision and trade-off notes.

## How I know it works

The first nine rows below are the required edge-case scenarios from section 8 of the build plan; the remaining seven are its acceptance criteria. Evidence references actual tests, reports, or queries.

| Requirement | Evidence |
|---|---|
| Edge 1: malformed CSV row | `tests/test_edge_cases.py::test_malformed_csv_is_rejected_and_run_continues` |
| Edge 2: missing required field | `tests/test_validate.py::test_first_reason_codes_and_priority` |
| Edge 3: duplicate delivery/key collision | `tests/test_ingest.py::test_insert_versions_is_idempotent_and_counts_conflicts`; `tests/test_validate.py::test_duplicate_key_winner_does_not_depend_on_input_order` |
| Edge 4: unexpected schema change | `tests/test_edge_cases.py::test_schema_mismatch_marks_run_failed_and_extra_columns_warn` |
| Edge 5: empty batch | `tests/test_edge_cases.py::test_zero_byte_batch_succeeds_without_changing_published_outputs` |
| Edge 6: partial publish failure and retry | `tests/test_publish.py::test_fault_mid_publish_rolls_back_and_failed_run_is_logged` |
| Edge 7: late/out-of-order version | `tests/test_e2e.py::test_record_in_second_file_with_older_timestamp_does_not_replace_golden_values` |
| Edge 8: invalid source reference | `tests/test_validate.py::test_first_reason_codes_and_priority`; sample reject counts in [reports/reconciliation.md](reports/reconciliation.md) |
| Edge 9: same input rerun | `tests/test_pipeline_e2e.py::test_rerun_is_idempotent_review_decisions_persist_and_empty_leaves_outputs` |
| Acceptance 1: keys and referential integrity | `tests/test_db.py::test_foreign_keys_and_status_checks_are_enforced`; orphan/FK queries in [sql/sample_queries.sql](sql/sample_queries.sql) |
| Acceptance 2: deterministic transforms | `tests/test_pipeline_e2e.py::test_shuffled_rows_and_reversed_files_produce_same_golden_tables` |
| Acceptance 3: counts and aggregates reconcile | [reports/reconciliation.md](reports/reconciliation.md); publish assertions and `sql/sample_queries.sql` |
| Acceptance 4: invalid records traceable | `tests/test_ingest.py::test_wrong_column_count_is_structural_reject_and_read_continues`; reject fields in [docs/DATA_DICTIONARY.md](docs/DATA_DICTIONARY.md) |
| Acceptance 5: reruns create no duplicates | `tests/test_pipeline_e2e.py::test_rerun_is_idempotent_review_decisions_persist_and_empty_leaves_outputs` |
| Acceptance 6: tests pass | The saved run in [reports/pytest_output.txt](reports/pytest_output.txt) shows 91 passed in 1.37s on Python 3.11.18; the separate Phase 8C clean-clone run passed 91 in 1.80s. |
| Acceptance 7: clean-environment setup | Phase 8C clean-clone verification is complete; details and sample CSV comparisons are in the section above. The exact clean-clone console log is not saved in this repository. |

## Limitations and next steps

- Nickname and address-abbreviation lists are small and English/India focused; transliteration handling is not implemented.
- Name handling only reorders simple `Last, First` values. Single-token names cannot meet the compatible-name gate and are review-only at best; `jonathan` and `john` share a canonical form by design.
- Naive timestamps are assumed UTC. Reject idempotency assumes unique file basenames.
- Whitespace-only or case-only raw changes create a new version even if normalized values are unchanged.
- Hand-tuned weights and thresholds were evaluated on synthetic data and need validation on real, representative data.
- Golden IDs change when cluster membership changes; no golden ID history table is implemented.
- Review decisions persist but are not applied to clustering.
- Capped blocks can lose recall. The 100K benchmark skipped 2,513,750 potential pairs across three capped blocks.
- Batch-only SQLite operation; a single writer is expected. Incremental matching and multi-writer operation are not implemented.
- Only the customer entity is implemented.

Potential next steps listed in the plan: apply review decisions as cluster edges, add golden ID history, investigate Fellegi-Sunter probabilities, add a PostgreSQL target, incremental blocking, and data-quality dashboards.

## Synthetic data and AI usage

All committed sample and generated benchmark records are synthetic. Do not treat identifiers or measured quality as representing real people or production populations. Ground truth is synthetic and is only consumed by evaluation tooling.

AI tool usage, development contributions, personal verification activities, and limitations of the prompt archive are documented in [AI_USAGE.md](AI_USAGE.md).

## Project layout

```text
config/                 TOML thresholds, weights, priorities, normalization maps
data/sample/            committed synthetic CSV sample
docs/                   build plan and generated data dictionary
prompts/                prompt-session records
reports/                saved reconciliation, evaluation/performance evidence, pytest output
sql/                    review/reconciliation query examples
src/dedup/              CLI, pipeline stages, schema, rules, generator and evaluator
tests/                  unit, database, integration, edge-case and SQL tests
DESIGN_NOTES.md         decisions and trade-offs
AI_USAGE.md             AI and personal-verification record
environment.yml         Conda environment definition
pyproject.toml          package metadata and CLI entry point
```
