# Design notes

These notes describe the implementation in `src/dedup/`, as checked against `docs/BUILD_PLAN.md`, tests, configuration, SQL, saved reports, and recovered development prompts. The `prompts/` directory contains the initial project brief and recovered development-session prompts for Phases 0–2, 3–7, and final documentation and clean-clone work. The archive may not contain every historical prompt; missing prompts have not been reconstructed.

## Assumptions

| ID | Assumption and consequence if it is wrong |
|---|---|
| A1 | The implemented entity is customers. The committed sample and benchmark inputs are synthetic; metrics do not transfer to real data. |
| A2 | Email and phone can be shared by family members or role accounts. Shared-name conflict gates send some cases to review; block caps reduce extreme blocks but may lose recall. |
| A3 | `(source_system, source_native_id)` identifies one logical record. A source reusing that key for a different person can make unrelated data appear to be versions of one record. |
| A4 | `updated_at` is business version time; naive timestamps are interpreted as UTC. A source using local time without an offset can cause wrong current-version selection. |
| A5 | Phone normalization targets Indian ten-digit numbers after removing a leading `0` from 11 digits or `91` from 12 digits. Other lengths become NULL and the row is kept; international phone formats may lose matching evidence. |
| A6 | Configured source priority is CRM (1), WEB (2), IMPORT (3). Different priorities can change survivorship results. |
| A7 | The decision policy treats a wrong auto-merge as more costly than a missed duplicate; uncertainty is routed to review. This is a design preference, not a measured business cost model. |
| A8 | Reject idempotency identifies a row by source-file basename, row number, and raw-line hash. Distinct files with the same basename and matching row position/content can collide. |
| A9 | A DOB conflict blocks auto-merge: when a strong identifier also exists, the pair is reviewed; without one, it is a non-match. Incorrect DOB data can therefore defer true duplicates or exclude pairs. |
| A10 | Full recomputation is acceptable for the measured 100,000-row input on the machine described in `reports/performance.md`; this is not a capacity guarantee for other machines or data. |
| A11 | SQLite is used with one writer at a time. Concurrent pipeline runs are not a supported operating mode. |
| A12 | Generator entity IDs define truth for evaluation. Metrics describe the generator's noise model, not an external ground-truth standard. |

## Decisions

### D1–D11 from the build plan

| ID | Decision | Reason and cost |
|---|---|---|
| D1 | Model customers, not products. | The customer problem includes shared identifiers and family cases. Product entities and their identity rules are outside the implemented scope. |
| D2 | Use SQLite and Python's standard library for storage/orchestration. | This keeps local setup small and supplies transactions; SQLite has a single-writer limit. |
| D3 | Implement blocking, scoring, classification, clustering, and survivorship in project code; use RapidFuzz for string similarity. | The rules are visible and testable. Hand-built rules need tuning and maintenance; RapidFuzz remains an external dependency. |
| D4 | Let evidence gates decide and scores rank evidence. | This prevents a high renormalized score from making an email-only pair merge automatically. More uncertain pairs need review. |
| D5 | Keep source-record, content-version, and run identities separate. | Updates remain in raw history and duplicate deliveries can be recognized. The schema and reconciliation carry more identifiers and counts. |
| D6 | Recompute derived output from all append-only history. | This supports deterministic ordering and late-data handling; compute and storage work grow with history. |
| D7 | Publish derived tables in one transaction. | A publish failure preserves the previous output. The transaction can make publishing a sizeable batch of work. |
| D8 | Regenerate `review_queue` but preserve decisions in `review_decisions`. | Publishing cannot erase a stored decision. Decisions are currently displayed but do not affect clustering. |
| D9 | Keep tuning, evaluation, and performance runs separate in intent. | The evidence includes the seed-1 profile comparison, independent seed-2 evaluation, and seed-3 performance measurements. These remain synthetic experiments and do not establish real-world accuracy. |
| D10 | Derive data IDs from stable meaningful inputs; use a separate execution ID for each run. | IDs are repeatable for identical source keys/content or cluster membership. Golden IDs change when membership changes, and `run_id` is intentionally nondeterministic. |
| D11 | Store thresholds, weights, source priorities, and tolerance in TOML and snapshot run configuration. | A run records its settings for interpretation. Configurable values still require calibration for real source data. |

### Section 4 decisions: options and consequences

**Storage — SQLite and the standard library.** Considered SQLite versus PostgreSQL, DuckDB, and a pandas-centered approach. SQLite was chosen because the project can initialize a local database and use actual transactions without a separate service. The cost is a single-writer model and a batch-oriented local database rather than a concurrent service deployment.

**Matching — weighted score with evidence gates.** Considered rules only, Fellegi–Sunter, machine learning, and packages such as `recordlinkage` or `dedupe`. The implementation uses explicit project rules and weighted feature scores, with RapidFuzz only for string similarity. This makes each gate inspectable and avoids relying on a black-box merge decision. The costs are hand-tuned weights and thresholds, more code to maintain, and no evidence that the settings generalize beyond synthetic data.

**Blocking — union of three keys with a cap.** Considered a single key, no blocking, and locality-sensitive hashing. Email, phone, and a Soundex/initial/postcode composite key form a deduplicated candidate union; blocks above the configured cap are skipped. This sharply reduces comparisons in the measured runs and records potential skipped pairs. The cap can remove true candidates; the 100K synthetic run skipped 2,513,750 potential pairs across three blocks. The 2K seed-3 experiment measured 95.5939% blocking recall, but had no capped blocks.

**Recompute — full calculation from raw history.** Considered incremental merging. Full recomputation was chosen to make current-version selection, late arrivals, and input order easier to reason about. The cost is work that grows with the entire retained history; incremental processing is not implemented.

**Publish — one transaction.** Considered row-by-row/upsert publication. A single transaction makes the derived output an all-or-nothing replacement, and the fault-injection test checks rollback and retry. Its cost is a larger write transaction and SQLite's single-writer constraint.

**Uncertain matches — review queue.** Considered merging on score or dropping uncertain pairs. A persisted review queue exposes uncertainty and avoids automatically merging guarded pairs. This lowers automatic recall and requires human review; decisions are not yet applied to clustering.

**Review decisions — separate persistent table.** Considered deleting decisions when the generated queue is replaced. A separate table preserves decisions across publishes, and the CLI upserts a decision by `pair_id`. It adds state to maintain, and current decisions are not consumed as clustering edges.

**Golden ID — hash of sorted member IDs.** Considered random UUIDs and the minimum member ID. The membership hash is deterministic for a given cluster and independent of member ordering. Its cost is that a membership change changes the golden ID; golden ID history is not implemented.

**Configuration — TOML with argparse CLI.** Considered YAML and hardcoded values. TOML uses Python's `tomllib` without another parsing dependency, and argparse defines the commands. Values remain explicit in config, but changing them requires an appropriate evaluation; the CLI does not expose every setting as an override.

## Additional implementation decisions

These points are recorded in the existing Phase 1/2A/2B/6 notes in this file and verified against code:

- `reject_id` is a SQLite `INTEGER PRIMARY KEY`; the plan did not assign a deterministic reject ID formula.
- `row_hash` hashes the original field values in a fixed order, mapping Python `None` optional values to empty strings before joining with `\x1f`.
- An injected naive clock for a run ID is treated as UTC; the run ID includes a UTC compact timestamp plus four hex characters.
- Schema initialization upserts configured source priorities. Starting a run marks older `running` rows abandoned before inserting the new run.
- The run table records additional reconciliation counts including `valid_rows`, `records_in_merged_clusters`, and `records_in_pending_review`.
- Generator defaults are seed 1, duplicate rate 0.35, family rate 0.10, invalid rate 0.14, and late rate 0.10. It uses project word lists and `random.Random(seed)`, not Faker. Duplicate/family/late generation and rounded invalid-row injection follow the existing `DESIGN_NOTES.md` phase notes and `src/dedup/generator_*.py` implementation.
- Raw `source_system` retains its received value; `source_system_key` stores its trimmed uppercase form for validation and foreign-key linkage.
- `review-decide` upserts one current decision by `pair_id`, replacing its prior decision/reviewer/time/note. It does not remove or rewrite decisions during publish.
- `run --as-of` supplies a reference time for future-timestamp validation; the generator uses fixed date ranges. This makes generated runs and tests independent of the wall clock when an as-of value is supplied.
- Nickname canonicalization is a single-step lookup; `Last, First` is reordered before name normalization. Blocking uses only the implemented keys and cap.

The recovered prompt archive is maintained under `prompts/`. It preserves original user instructions where available, but it is not a complete record of every development conversation. The implementation details above are verified against the current code and tests; recovered prompts provide additional context where available.

## Trade-offs and limitations

| Choice | Gain | Cost / limitation | Evidence or containment |
|---|---|---|---|
| Precision-oriented gates and review | Guarded merges and visible uncertainty | Lower automatic recall and review workload | Decision tests, review counts, and synthetic evaluation reports |
| Full recompute | Straightforward deterministic backfill | Runtime grows with retained history | 100K run in `reports/performance.md`; incremental design is not implemented |
| Content-version history | Keeps changed deliveries | Whitespace/case-only raw changes create versions | Current-version selection and idempotent insert tests |
| Membership-hash golden IDs | Stable for unchanged membership | Membership changes change IDs | `tests/test_ids.py`; golden ID history is not implemented |
| Hand-tuned rules and weights | Inspectable behavior | Settings may not generalize | Synthetic-only evaluation; needs representative labeled data |
| Block cap | Limits very large candidate blocks | Can lose recall | Three capped blocks skipped 2,513,750 potential pairs in the 100K seed-3 benchmark; 2K seed-3 blocking recall was 95.5939% without capped blocks |
| Persistent review decisions | Decisions survive regenerated queues | They are not applied to clustering | `tests/test_pipeline_e2e.py::test_rerun_is_idempotent_review_decisions_persist_and_empty_leaves_outputs` |
| SQLite | Local setup and transactional publish | One writer at a time | `src/dedup/db.py`; no concurrent-run guarantee |
| Batch pipeline | Simple whole-history recomputation | No streaming or incremental processing | `src/dedup/pipeline.py`; this project is batch-only |
| RapidFuzz | Jaro-Winkler and token-set similarity | Additional pinned dependency | `pyproject.toml`; decision logic remains in project code |

Explicitly, nickname mappings and address abbreviations are small and India/English focused. There is no transliteration handling. Weights and thresholds are hand-tuned using synthetic data. Golden ID history is not implemented. Review decisions persist but are not applied to clustering. Evaluation and performance measurements use synthetic data and do not establish production accuracy.

Potential next steps, not implemented features: apply review decisions as clustering edges, maintain golden ID history, investigate Fellegi–Sunter probabilities, add a PostgreSQL target, implement incremental blocking, and add data-quality dashboards.

## Testing approach

- Unit tests cover IDs, ingest, validation, normalization, blocking, scoring, classification, clustering, and survivorship. Hard-coded ID values and the eight-row classifier decision table have direct tests.
- Integration tests cover stage 1, pipeline publish, reconciliation, reruns, empty input, shuffled rows/reversed files, and exports.
- Fault injection raises during publish and checks the previous published state, failed-run record, and successful retry.
- Evaluation tests use hand-built truth; generator tests check seeded output and truth structure. `tests/test_sql_queries.py` exercises the SQL query examples.
- The saved `reports/pytest_output.txt` transcript records `.venv\Scripts\python.exe -m pytest -p no:cacheprovider --basetemp=test-temp`: **94 passed in 1.72s on Python 3.11.18 (Windows)**. The separate Phase 8C clean-clone run passed 91 in 1.80s; its console output was not saved. These are automated test results, not manual review evidence.
- Tests do not establish production accuracy, behavior under concurrent writers, or transliteration/name coverage outside the implemented rules.


## How I know it works

| Evidence question | Evidence available | Status / limit |
|---|---|---|
| Do the runtime count and referential-integrity identities reconcile? | Assertions in `src/dedup/publish.py`; `sql/sample_queries.sql`; `reports/reconciliation.md` | Sample report records all listed identities passing, zero lineage orphans, and zero FK violations. |
| Is output stable under input order changes and reruns? | `tests/test_pipeline_e2e.py::test_shuffled_rows_and_reversed_files_produce_same_golden_tables`; `tests/test_pipeline_e2e.py::test_rerun_is_idempotent_review_decisions_persist_and_empty_leaves_outputs` | Automated test evidence; manual activity is separate. |
| Does publish failure preserve the previous output? | `tests/test_publish.py::test_fault_mid_publish_rolls_back_and_failed_run_is_logged` | Automated fault-injection test also retries successfully. |
| Is accuracy measured on independent seed-2 data? | `reports/seed2_evaluation.json` | Completed on independent synthetic data: precision 1.0000, recall 0.7235, F1 0.8396. Not a real-world accuracy guarantee. |
| Were review cases and lineage manually inspected? | `AI_USAGE.md`; `reports/manual_reconciliation_check.md` | Twenty review-queue pairs and one three-member golden cluster were manually inspected. The examples are synthetic and not statistically representative. |
| Is performance measured? | `reports/performance.md` reports the seed-3 2K and 100K experiments | Synthetic benchmark only; not a production capacity/accuracy claim. |
| Was setup verified from a clean clone? | Phase 8C verification: public clone at `D:\\PROJECTS\\TESTING_DEDUP\\customer-dedup-pipeline`, commit `0d8a73e`; fresh Conda `dedup-clean`; README install/sample workflow; byte comparison against committed sample outputs | Clean-clone verification is DONE. The exact console log was not saved in the repository. |
| Did the full suite pass? | `reports/pytest_output.txt` contains one saved run | Saved transcript: 94 passed in 1.72s on Python 3.11.18 (Windows). Separate Phase 8C clean-clone run: 91 passed in 1.80s; its exact console output is not in the repository. |
