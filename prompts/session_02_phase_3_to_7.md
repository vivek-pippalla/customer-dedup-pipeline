# dedup project Phase 3to7


> Task: Phase 3. Read BUILD_PLAN sections 3.2, 3.3, 3.11, 5 and 9. Follow the standing rules.
> Build:
> 1. src/dedup/normalize.py: all derived fields in section 3.2 as pure functions plus normalize_row(raw) -> NormalizedRow; a hand-written soundex(); nickname map loaded from config/nicknames.toml. Phone failures return None and are counted, never raised.
> 2. src/dedup/validate.py: validate_rows(rows, run_started_at, source_systems, tolerance_hours) -> (valid_rows, rejects) implementing exactly the row-level rules and reason codes in section 3.3, including the order-independent duplicate_key rule (same source_record_id + same updated_at_utc, different content: keep the smallest row_hash, reject the rest). A row gets the first failing reason in this order: missing_required, invalid_source_system, invalid_email, invalid_timestamp, future_timestamp, duplicate_key. Rejects carry source_file, source_row_number, reason_code, raw_line.
> 3. src/dedup/pipeline.py: stage1_ingest(conn, paths, config, run) that, per file: reads the batch, handles file_error (run failed, clear message, nothing else processed) and empty batches (run success_empty), merges structural rejects with validation rejects, then in ONE transaction inserts versions (ON CONFLICT DO NOTHING), inserts rejects (ON CONFLICT on the UNIQUE key DO NOTHING, but still counted for the run), and inserts clean_customers rows for new versions. Returns the counts from section 3.11 and metrics (phone_invalid, rejects by reason, warnings).
> 4. Wire `dedup run --input FILE [FILE ...] --db PATH --config PATH [--as-of ISO_TIMESTAMP] [--log-level LEVEL]` to: init schema if needed, mark abandoned runs, start the run, run stage 1, finish the run with counts (config_snapshot includes as_of). For now it stops after stage 1 and prints a summary table (input rows, rejected by reason, new versions, duplicate events).
> Tests (tests/test_normalize.py, test_validate.py, test_stage1.py): one test per reason code; each normalization rule with edge cases (91 prefix, 11-digit leading 0, 9-digit phone becomes None and row is kept, accents, titles, 'Last, First' reordering, single-step nickname lookup (jon, johnny, jonathan -> john; no chaining; unmapped names unchanged), abbreviations, initial-only first names, one-character name valid); future timestamp inside tolerance accepted, outside rejected (pass an explicit as-of value so the test never depends on the wall clock); duplicate_key keeps the same row regardless of row order (shuffle test); the batch identity input_rows = rejected + new_versions + duplicate_events holds on a mixed file; running the same file twice gives new_versions=0 the second time and the same reject count in the run summary without adding duplicate rows to rejects; file with missing column marks the run failed and leaves tables unchanged; empty batch gives success_empty.
> Done when: running the CLI on data/sample/customers_sample.csv prints a correct summary and the test suite passes.




> Task: Phase 4A. Read BUILD_PLAN sections 3.5 and 3.6. Follow the standing rules.
> Implement:
> 1. src/dedup/blocking.py: build_blocks(records, block_cap) for the three keys in section 3.5, returning candidate pairs as a sorted deduplicated list of (id_a, id_b) with id_a < id_b, plus a BlockingStats object: comparisons_naive, comparisons_blocked, reduction_ratio, per-key block counts, capped_blocks (count, top 20 largest keys with sizes, and the number of pairs skipped because of the cap). Records are the current versions of each source record (a helper current_versions(conn) in pipeline.py or a new function selects, for each source_record_id, the version with the latest updated_at_utc, ties broken by the smallest row_hash). Also expose a pure helper block_keys(record) -> list of (key_type, key_value) so the evaluator can tell whether a missed pair shared a block key. Pure functions over in-memory dicts; no database access in blocking.py.
> 2. src/dedup/scoring.py: score_pair(rec_a, rec_b, weights) -> PairFeatures with the five feature values (None when missing on either side), score (renormalized weighted sum over present features), coverage, plus the flags strong_id, dob_conflict, shared_conflict, names_compatible exactly as defined in section 3.7 (flags only; no decision yet). Use rapidfuzz JaroWinkler and token_set_ratio. last_name_min_jw comes from config.
> Tests (tests/test_blocking.py, test_scoring.py): pairs are canonical and deduplicated; result identical after shuffling input; a record without email still pairs through phone or the soundex key; blocks above the cap are skipped and reported with the right skipped-pair count; reduction ratio computed correctly on a hand-built set; renormalization example from section 3.6 (email-only match gives score 1.0 but coverage 0.30); each flag is tested with positive and negative cases, including Jon/John/Jonathan canon, initial-only names, missing last name, and a DOB mismatch.
> Do not classify yet. Show me the BlockingStats for the sample file.




> Task: Phase 4B. Read BUILD_PLAN sections 3.7 and 3.12. Follow the standing rules.
>
> Implement:
> 1. src/dedup/classify.py: classify_pair(features, thresholds) -> Decision(decision, reason_code, match_tier) implementing the 8-row decision procedure in section 3.7 literally, top to bottom, first match wins. match_tier is "exact" only when decision is auto_merge, email_norm equal, name_norm equal, and phone_norm equal when both present; otherwise "probable". Write the decision table as a documented constant so the README can quote it.
> 2. A pipeline function classify_all(records, pairs, config) -> list of classified pairs, deterministic order (sorted by pair_id).
> 3. src/dedup/evaluate.py (thin version) and `dedup evaluate --db PATH --truth PATH`: pairwise precision, recall and F1, where predicted pairs are all pairs of records in the same golden cluster. Because clustering is Phase 5, for now evaluate auto_merge pairs only and label the output "auto_merge pairs only (pre-clustering)". Also report: true duplicate pairs found in auto_merge, in review, and missed entirely; review queue size; false auto-merges listed with their reason codes and features (top 20) so I can inspect them. Evaluation counts only valid rows that exist in the database; ground-truth rows flagged invalid must match rejects (report agreement). Split the true pairs that were NOT predicted into: not_blocked (no shared block key at all), lost_to_cap (they share a block key but every shared key was capped), and scored_non_match (they were candidates and classified non_match; show the reason_code); pairs sitting in the review queue are reported separately, not as misses. Report blocking recall (true pairs that appear as candidates / all true pairs) next to final recall.
>
> Tests (tests/test_classify.py, test_evaluate.py): one test per row of the decision table (all 8) with hand-built features; the worked example (email-only, different names) gives review/shared_identifier_only; family pair (same email, different first names) gives review/shared_identifier_conflict; same phone Jon vs Jonathan gives auto_merge; different DOB with same email gives review/dob_conflict; names only similar gives review/name_only or non_match/low_score; case/whitespace email variants produce match_tier exact; evaluator math checked on a tiny hand-built truth set with known precision and recall; a hand-built pair that shares only a capped key lands in lost_to_cap.
>
> Then run the pipeline on a 5,000-row dev file (seed 1) and show me the real evaluator output. Do not tune anything yet.




> Task: Phase 5. Read BUILD_PLAN sections 3.8, 3.9 and 3.10. Follow the standing rules. This phase builds pure in-memory logic; it does not write to the database.
> Implement:
> 1. src/dedup/cluster.py: union-find over auto_merge pairs; the root is always the smallest source_record_id; build_clusters(record_ids, auto_pairs) -> clusters sorted by root. check_clusters(clusters, records) compares ALL member pairs of every cluster of size >= 3 (even pairs never scored) for DOB conflict and first-name conflict (both non-initial, different canonical first names). A conflicting cluster is split into singletons and its pairs are returned as demoted review pairs with reason transitive_conflict. Return (final_clusters, demoted_pairs).
> 2. src/dedup/survivorship.py: build_golden(cluster, records_by_id, source_priority) -> GoldenRecord with the survived value per field, the chosen source_record_id and version_id, and the rule_applied label, using exactly the rule chains in section 3.9 (each rule step gets a distinct, readable rule_applied string such as "latest_updated_at" or "tie_break_smallest_id"; a field with no candidate gets value None and rule "no_value"). Also compute golden_id, member_count, match_tier summary and latest_updated_at_utc. Singletons also become golden records so every valid source record is represented.
> 3. A pipeline function compute_all(conn, config) -> ComputeResult that loads current versions, blocks, scores, classifies, clusters, applies conflicts, builds golden records, and returns golden records, members, lineage rows, candidate pairs, review pairs, and counts. Still no DB writes.
> 4. Update evaluate.py to use the final clusters for predicted pairs (all pairs within a cluster), keeping the auto_merge-only number as a second line.
> Tests (tests/test_cluster.py, test_survivorship.py): chain A-B, B-C auto-merged gives one cluster; chain where A and C have different DOBs is demoted with transitive_conflict and produces three singletons plus review pairs; cluster result identical after shuffling inputs; root is the smallest id; each rule in the table has a test for each step (the winner and the fallback), including: longest non-nickname name beats "Jon", priority beats recency for email, recency beats priority for phone, majority DOB, most-complete address, postcode following the address winner, all-null field gives no_value; golden_id equals the hash of sorted member ids; lineage has one row per field; every lineage source_record_id belongs to the cluster; late data: an older version arriving later never replaces newer values.
> Show me one real cluster from the dev file with its lineage rows, so I can verify it by hand.



> Task: Phase 6. Read BUILD_PLAN sections 2, 3.11, 5 and 9. Follow the standing rules.
> Implement:
> 1. src/dedup/publish.py: publish(conn, result, run_id) that, inside ONE transaction() (BEGIN IMMEDIATE ... COMMIT), deletes and reinserts golden_customers, golden_members, golden_lineage, candidate_pairs and review_queue for the current computation. review_queue.status is filled by LEFT JOIN with review_decisions on pair_id (default "pending"). NEVER delete or modify review_decisions. Order deletes children first so foreign keys hold. Accept an optional fault_hook(callable) invoked after the deletes and midway through the inserts so tests can inject an exception; the hook must be None in normal use. On any exception the transaction rolls back and the exception propagates.
> 2. Complete pipeline.run_pipeline(paths, config, ...): mark abandoned runs, start the run (committed), stage 1 (its own transaction), stage 2 compute, stage 3 publish, then finish the run with all counts from section 3.11 and metrics_json (blocking stats, capped blocks, rejects by reason, phone_invalid, decision counts including non_match, warnings). On any exception: ensure rollback, finish the run as "failed" with the error text (never raises past the run log), then re-raise as a clean CLI error with a non-zero exit code. Log stage start and end with counts at INFO, validation warnings at WARNING, and the failure with exc_info at ERROR. On an empty batch: status success_empty, and published output is left untouched (still run stage 1 bookkeeping).
> 3. Reconciliation assertions: after publish, run the identities in section 3.11 as code and store the result in metrics_json. If an identity fails, the run is "failed" with a message that names the identity and both sides of the equation (the publish has already rolled back in that case: run the checks inside the publish transaction before COMMIT).
> 4. `dedup report --db PATH --out reports/reconciliation.md`: writes the run summary, the three identities with real numbers, rejects by reason, top 10 largest clusters, review queue size by reason code, capped blocks, and a data-quality section (null rate per field in clean_customers, phone_invalid count, warnings such as extra columns), all queried from the database. Also export golden_customers, golden_lineage, review_queue, rejects as CSV into a given folder (--export-dir). Exports must omit run_id, first_seen_run_id and any timestamp column that describes the execution rather than the data, and must be sorted by primary key, so the same input always gives byte-identical files (the clean-clone check diffs them).
> 5. A small helper for tests/demo: `dedup review-decide --db PATH --pair-id ID --decision merge|not_merge --reviewer NAME --note TEXT` that inserts into review_decisions (ON CONFLICT (pair_id) DO UPDATE is acceptable here, and keep a note about it in DESIGN_NOTES).
> Tests (tests/test_publish.py, test_pipeline_e2e.py): after a successful run, golden_members count equals unique_source_records; fault injected mid-publish leaves the previous golden tables byte-identical (compare row counts and a hash of ordered rows) and the run marked failed; rerunning after the failure succeeds and matches a clean run; running the same input twice gives identical golden ids, identical table contents and no new raw rows; a review decision inserted before a rerun is still present after it and shows in review_queue.status; a failed identity check rolls back; orphan checks return zero; shuffled row order and reversed file order give identical golden tables; empty batch leaves outputs unchanged; exports from two runs of the same input are byte-identical; the run command has no argument for ground-truth files and no module except evaluate.py opens one.
> Done when: the full pipeline runs end-to-end from the CLI on the sample and dev files and all tests pass.



> Task: Phase 7A, complete the test suite. Read BUILD_PLAN section 8 (test matrix). Follow the standing rules.
> First list which rows of the section 8 matrix are already covered by existing tests (file and test name). Then add only what is missing in tests/test_edge_cases.py and tests/test_e2e.py, one test per scenario, using tmp_path databases and hand-built CSV fixtures. Do not duplicate coverage. Then save the full pytest output (python -m pytest -v) to reports/pytest_output.txt. Do not edit the output by hand.
> Additional property-style tests: shuffled rows and reversed file order give identical golden tables, identical lineage and identical review queue; two runs of the same input give identical table hashes except run_id and timestamps; a transitive chain with a conflict at the ends goes to review; a record that appears in two files, older version second, produces the newer values in the golden record.
> Report any test that fails and what it reveals. Do not weaken a test to make it pass; if you believe a test is wrong, explain why and ask me.




> Task: Phase 7B, evaluation. Read BUILD_PLAN sections 3.6, 3.7, 3.11 and 3.12. Follow the standing rules.
> Protocol: generate a dev file with seed 1 (20,000 rows) and a final file with seed 2 (20,000 rows). Tune ONLY on seed 1. Write scripts/tune.py that tries a small grid (auto in 0.85..0.95, review in 0.55..0.75, last_name_min_jw in 0.85..0.95, and 3 alternative weight sets that each sum to 1.0), runs the full pipeline into a temporary database for each combination, evaluates against the dev ground truth, and prints a table of precision, recall, F1, review queue size, and false auto-merge count. Choose the operating point that keeps auto-merge precision as high as possible (target: no worse than 0.99) while keeping recall reasonable, and state why. Do not choose the operating point silently: show me the table and recommend one, then wait for my confirmation before editing config/default.toml.
> After I confirm: run the final seed-2 file ONCE with the chosen config and write reports/evaluation.md with the real numbers: pairwise precision, recall, F1 (cluster-based), auto-merge-only precision, share of true duplicate pairs in auto_merge / review / missed (missed split into not_blocked, lost_to_cap, scored_non_match) and blocking recall, review queue size and breakdown by reason, ground-truth invalid rows versus actual rejects, and the 20 worst false auto-merges and 20 top missed pairs with features. Add a short plain-language interpretation and the limitations (synthetic data). Every number must come from a run; include the command lines used.



> The 32-trial results are promising. However, before changing config/default.toml, I want a fair comparison against the actual original defaults from Build Plan v3.
>
> Please:
>
> 1. Run the original default configuration on the existing seed-1 20K dataset and its ground truth.
> 2. Record cluster precision, recall, F1, auto-merge precision, false auto-merges, and review queue size.
> 3. Compare those results against the recommended name-forward configuration:\
>    auto=0.85, review=0.75, last_name_min_jw=0.85.
> 4. Do not regenerate datasets, rerun the 32-trial grid, evaluate seed 2, or modify config/default.toml.
> 5. Save the comparison results and report the actual differences.
>
> Use the existing generated datasets and preserve reproducibility. Do not invent or estimate missing metrics.



> I want to investigate the actual production performance of our customer deduplication pipeline.
> Important distinction: the previous 42-minute run was a multi-configuration tuning experiment. I want to know how long ONE complete pipeline execution takes on 20,000 records.
>
> Please:
>
> 1. Use the existing seed-1 20K dataset.
> 2. Use a separate temporary SQLite database so existing project data is not modified.
> 3. Use the currently selected configuration.
> 4. Run the complete pipeline exactly once.
> 5. Measure wall-clock runtime separately for:
>    - CSV ingestion
>    - Validation and normalization
>    - Blocking
>    - Similarity scoring
>    - Classification
>    - Clustering
>    - Survivorship and lineage
>    - Publishing
>    - Total runtime
> 6. Record:
>    - Input rows
>    - Valid and rejected rows
>    - Unique source records
>    - Candidate pairs
>    - Naive comparison count
>    - Blocking reduction ratio
>    - Golden records
>    - Merged records
>    - Review queue size
>    - Peak memory usage if available
> 7. Verify reconciliation and output correctness.
> Do not run a tuning grid, regenerate data, evaluate seed 2, change thresholds, or modify production configuration.
> Report the actual measured runtime and bottleneck. Do not estimate or invent timings.



> Task: Phase 7C, performance. Read BUILD_PLAN sections 3.5 and 3.12. Follow the standing rules.
> Additional benchmark requirements:
> 1. In the 2,000-row naive-versus-blocked experiment, use identical scoring logic and feature calculations for both approaches.
> 2. Measure blocking generation time separately from candidate-pair scoring time.
> 3. Use ground truth only in the evaluation step to calculate true-pair blocking recall. Never pass ground truth to ingestion, blocking, scoring, or the production pipeline.
> 4. Report Python-tracked memory and process-level memory separately if both are available. Clearly identify the measurement method.
> 5. Preserve existing datasets, databases, and reports. Use fresh output paths for the 100K benchmark.
> 6. Record the exact configuration snapshot used for the benchmark so the results can be reproduced.


> Task: Phase 7D. Follow the standing rules. Write sql/sample_queries.sql with commented queries that I can run in the sqlite3 shell against a pipeline database: (1) the three reconciliation identities from BUILD_PLAN section 3.11 returning expected vs actual; (2) orphan checks for every foreign key (each must return 0); (3) rejects by reason; (4) top 10 clusters by member_count with their members; (5) "three source rows became one golden record" for a specific golden_id including each field's lineage; (6) the review queue with reason codes joined to both records' names, emails and phones; (7) records merged away per source system; (8) duplicate-event and new-version counts by run. Add tests/test_sql_queries.py that runs each query against a small pipeline database and asserts the expected results. Then run the sample file (data/sample/customers_sample.csv) through the pipeline and export the outputs to data/sample/output/ (golden_customers, golden_lineage, review_queue, rejects as CSV) using `dedup report --export-dir`. Show me the query results.