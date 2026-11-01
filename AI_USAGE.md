# AI usage record

This document records the AI tools used during development, the extent of AI assistance, project decisions, and the verification activities performed.

## AI tools and models used

- **Antigravity:** IDE used for project development, code editing, terminal operations, and managing the project workspace.
- **OpenAI Codex:** AI coding extension used within Antigravity to assist with project implementation, code changes, debugging, testing, and documentation.
- **ChatGPT:** Used for project planning, technical discussions, reviewing implementation decisions, verification guidance, and documentation support during development.

Exact model identifiers were not retained. A prompt archive is maintained under `prompts/`, containing the initial project brief and recovered development-session records organized chronologically. The archive may not contain every historical prompt and is not presented as a complete record of every prompt used.

## Where AI generated most of the work

OpenAI Codex, used through the Antigravity IDE extension, provided the majority of the code-generation and implementation assistance.

AI assistance was used extensively across:

- Project scaffolding and configuration.
- Database schema, connection utilities, and data-access implementation.
- Synthetic data generation and CSV ingestion.
- Validation, normalization, blocking, matching, scoring, and classification.
- Clustering, survivorship, and field-level lineage.
- Pipeline orchestration, transactional publishing, and CLI commands.
- Automated tests, edge-case coverage, and end-to-end testing.
- SQL queries, reconciliation reports, performance reports, and project documentation.

Codex generated or modified substantial portions of the implementation. I directed the development workflow, provided requirements, reviewed outputs, ran tests and verification commands, and made or confirmed project-level decisions.


## What I rewrote, reviewed, or decided myself

I directed the project requirements and development workflow and made or confirmed the following decisions:

- Reviewed the matching thresholds and weight experiments on seed-1 data. I chose to retain the original thresholds and weights in `config/default.toml` rather than apply the experimental name-forward configuration.
- Kept the original configuration unchanged during the independent seed-2 evaluation. Seed-2 results were used for evaluation, not further tuning.
- Reviewed the matching, clustering, survivorship, lineage, and reconciliation design decisions and their documented limitations.
- Personally inspected 20 synthetic review-queue pairs, traced a golden customer through field-level lineage, and checked database reconciliation results against SQL queries.
- Reviewed the benchmark results, performance limitations, and clean-clone verification evidence.
- Reviewed the project documentation and checked key reported figures against the corresponding reports.

AI coding assistance generated or modified substantial portions of the application code. I am not claiming independent authorship of those implementation sections.

## Personal verification

Automated test results are evidence about automated checks; they are not personal/manual verification. The saved `reports/pytest_output.txt` transcript records **91 passed in 1.37s on Python 3.11.18**. The separate Phase 8C clean-clone run passed 91 tests in 1.80s; its exact console output is not saved in the repository.

- [x] Shuffle/reversed-file verification.
  - Test: `tests/test_pipeline_e2e.py::test_shuffled_rows_and_reversed_files_produce_same_golden_tables`
  - Method: Ran the targeted pytest independently from the project root.
  - Command: `python -m pytest tests\test_pipeline_e2e.py::test_shuffled_rows_and_reversed_files_produce_same_golden_tables -v -p no:cacheprovider --basetemp=test-temp`
  - Result: 1 passed in 0.24 seconds on Python 3.11.18 (Windows).
  - Conclusion: The test confirmed identical golden tables when input rows were shuffled and input files were processed in reversed order.

- [x] Trace one golden cluster through its lineage.
    - Database: `out/dev_seed1.db`
    - Golden ID: `g_00b07b3128850f94`
    - Golden customer: Rahul Das
    - Member count: 3
    - Source members: CRM (`crm-001765`), WEB (`web-001765`), IMPORT (`import-001765`).
    - Method: Queried `golden_customers`, `golden_members`, `clean_customers`, `raw_customer_records`, and `golden_lineage` using read-only SQLite queries.
    - Verified six field-level lineage entries: address, DOB, email, full_name, phone, and postcode.
    - All six fields traced to the CRM source record and the same source version.
    - Observed rules: `latest_updated_at`, `majority_value`, `source_priority`, and `follows_address_winner`.
    - Confirmed that the lineage run ID matches the golden record's run ID.
    - Conclusion: The selected golden values are traceable to their source record and field-level survivorship rules.
    - Limitation: The three source records largely agree on their values; this example does not independently validate survivorship behaviour across conflicting source values.

- [x] Inspect 20 review-queue items by hand.
    - Database: `out/dev_seed1.db`
    - Sample: 20 distinct pending review pairs selected reproducibly by `pair_id`.
    - Selection: 5 `dob_conflict`, 5 `shared_identifier_conflict`, 5 `shared_identifier_only`, 3 `name_only`, and 2 `score_below_auto`.
    - Method: Queried `review_queue`, `candidate_pairs`, `clean_customers`, and `raw_customer_records` using read-only SQLite queries. Selected current customer versions using latest `updated_at_utc`, with smallest `row_hash` as the tie-breaker.
    - Findings:
      1. DOB-conflict examples contained substantial differences in customer attributes despite shared identifiers.
      2. Shared-identifier conflicts demonstrated that a common email or phone alone is insufficient evidence for merging.
      3. Some shared-identifier-only pairs had high scores but first-name initials, so human review was appropriate.
      4. A name-only pair scored 1.0 but had only 0.35 coverage; the coverage gate prevented automatic merging.
      5. Score-below-auto examples were plausible matches that did not meet the automatic-merge threshold.
    - Conclusion: The inspected examples support the conservative classification approach.
    - Limitation: This was a manual inspection of 20 synthetic examples, not a statistically representative accuracy evaluation.
    - No matching logic or thresholds were changed.

- [x] Compare reconciliation figures against SQL query results.
  - Database: `out/dev_seed1.db`
  - Run ID: `run_20261031T142259Z_f24a`
  - Report: `reports/manual_reconciliation_check.md`
  - Method: Generated a fresh reconciliation report from the database and inspected all reported reconciliation identities, reject counts, cluster counts, and review queue counts.
  - Results: All eight reconciliation identities passed.
  - Verified counts: 5,000 input rows, 700 rejects, 4,300 valid rows, 4,062 unique source records, 3,259 golden records, and 803 merged-away records.
  - Verified that reject counts by reason sum to 700, golden member rows equal 4,062, lineage membership orphans are zero, and foreign-key violations are zero.
  - Observed 6,826 pending review pairs and no capped blocks or recorded warnings.
  - Conclusion: The generated reconciliation report is internally consistent with the database figures.
  - Additional observation: The latest successful run was a redelivery run with zero new versions and 4,300 duplicate events.

- [x] Review benchmark results and limitations.
  - Reports reviewed: `reports/performance.md` and `reports/seed1_20k_single_run_performance.md`.
  - Method: Inspected the recorded benchmark inputs, configuration, timing measurements, comparison counts, memory measurements, reconciliation results, and documented limitations.
  - 100K seed-3 benchmark: 100,000 input rows; 86,000 valid; 14,000 rejected; 81,092 unique source records; 64,250 golden records; 16,842 merged-away records; total runtime 450.995 seconds.
  - Stage review: Ingestion/validation/normalization took 218.151 seconds, while survivorship/lineage took 175.971 seconds. These were the largest measured stages.
  - Memory review: Python tracemalloc peak was 561.0 MiB; sampled process working-set peak was 1.356 GiB.
  - Blocking experiment: On 2,000 seed-3 rows, comparisons decreased from 1,304,920 to 1,690, with a 99.8705% reduction and 95.5939% true-pair blocking recall.
  - Limitations reviewed: The 100K naive comparison count is arithmetic only; three capped blocks skipped 2,513,750 pairs; the 2K recall result does not establish 100K recall; memory instrumentation adds overhead; and the 100K run did not use ground truth.
  - Cross-checked the key 100K and 2K benchmark figures in `README.md` against `reports/performance.md`; the runtime, row counts, comparison reduction, blocking recall, and memory measurements matched.
  - Conclusion: The measurements demonstrate substantial comparison reduction and provide useful runtime and memory baselines. They also identify blocking recall and ingestion/survivorship runtime as areas for future improvement.

- [x] Clean-clone setup verification.
  - Public clone at `D:\\PROJECTS\\TESTING_DEDUP\\customer-dedup-pipeline`, commit `0d8a73e`; fresh Conda environment `dedup-clean`; Python 3.11.18; `python -m pip install -e .` and `python -m pip install -e ".[dev]"` succeeded; CLI help listed six commands; sample pipeline counts were 50 input, 7 rejected, 43 valid, 41 unique source records, 32 golden records, 9 merged-away records, and 2 pending review pairs; pytest passed 91 tests in 1.80s; seed-3 2,000-row generate/run/evaluate succeeded; four sample exports matched `data/sample/output/` byte-for-byte with `fc /b`. The exact clean-clone console log is not saved in the repository.

- [x] Independently evaluate seed-2 data.
  - Dataset: `data/generated/final_seed2_20000.csv`
  - Ground truth: `data/generated/final_seed2_20000_truth.csv`
  - Database: `out/seed2_evaluation.db`
  - Run ID: `run_20261101T072455Z_e75c`
  - Configuration: `config/default.toml`, with original thresholds and weights unchanged.
  - Method: Ran the pipeline in a separate database and evaluated its results against the matching seed-2 ground-truth file.
  - Results: Precision 1.0000, recall 0.7235, F1 0.8396, blocking recall 0.9584, zero false auto-merges, and zero false cluster pairs.
  - True duplicate pairs: 5,436; recovered in final clusters: 3,933; pending review: 1,304; missed entirely: 221.
  - Invalid-row agreement: all 2,800 invalid truth rows matched persisted rejects.
  - Evaluation output saved in `reports/seed2_evaluation.json`.
  - Conclusion: The unchanged configuration achieved 100% precision on this independent synthetic dataset, with recall of 72.35%. No threshold or weight tuning was performed using seed-2 results.

## Other notes or disclosures

- OpenAI Codex, used through Antigravity, provided the majority of the code-generation and implementation assistance. ChatGPT was also used for planning, technical discussions, verification guidance, and documentation support.
- The project was developed with AI assistance under my direction. I provided requirements, guided the implementation workflow, reviewed outputs, ran tests and verification commands, and made or confirmed project-level decisions.
- The prompt archive under `prompts/` contains the initial project brief and recovered development-session records. It may not include every historical prompt. Missing historical prompts have not been invented or presented as original records.
- Automated test results and manual verification activities are documented separately. Manual verification claims in this record are limited to the activities I actually performed and the results observed.
- Benchmark results are based on synthetic datasets and the documented test environment; they should not be interpreted as production performance or real-world customer matching accuracy guarantees.