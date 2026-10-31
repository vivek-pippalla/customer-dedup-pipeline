# Phase 7C performance benchmark

This report contains measured results from synthetic seed-3 data. It describes one full 100,000-row run and a separate 2,000-row naive-versus-blocked scoring experiment. No ground-truth data was read by ingest, blocking, scoring, or the 100K pipeline run.

## Machine and measurement method

- OS: Windows 10, build 26300
- CPU: Intel(R) Core(TM) i7-8665U CPU @ 1.90GHz; 8 logical processors
- Installed RAM: 15.82 GiB, from Windows `GlobalMemoryStatusEx`
- Python: 3.11.18, 64-bit, Anaconda build
- RapidFuzz: 3.14.6
- Wall time: `time.perf_counter()` around the complete `run_pipeline` call and around the individual 2K operations
- Python memory: `tracemalloc` peak, one traceback frame
- Process memory: Windows `GetProcessMemoryInfo`, sampling working set every 50 ms

The 100K end-to-end wall time was measured while both memory trackers were active; the timing therefore includes their instrumentation overhead. Python-tracked allocations and sampled process working set are different measurements and are reported separately.

## Inputs and exact configuration

New, non-overwriting paths were used:

- `data/generated/phase7c_seed3_2000.csv` and matching truth/manifest files
- `data/generated/phase7c_seed3_100000.csv` and matching truth/manifest files
- `data/generated/phase7c_seed3_100000.sqlite` for the full 100K run

Both datasets were generated with seed 3 and the generator defaults: duplicate rate 0.35, family rate 0.10, invalid rate 0.14, late rate 0.10, one batch. The generator optimization used for the 100K generation preserves the old ordered random selection: a temporary regenerated 2K CSV and truth file compared byte-for-byte equal to the already generated 2K files.

The selected production configuration was read from `config/default.toml` without overrides. The 100K run stored this snapshot in its `runs.config_snapshot` (including its as-of value):

```json
{
  "as_of": "2026-10-31T00:00:00Z",
  "blocking": {"block_cap": 200},
  "logging": {"level": "INFO"},
  "paths": {"db": "out/dedup.db", "reports_dir": "reports"},
  "source_priority": {"CRM": 1, "IMPORT": 3, "WEB": 2},
  "thresholds": {"auto": 0.9, "last_name_min_jw": 0.9, "min_coverage": 0.5, "review": 0.65},
  "validation": {"future_tolerance_hours": 24},
  "weights": {"address": 0.1, "dob": 0.1, "email": 0.3, "name": 0.25, "phone": 0.25}
}
```

Commands used to create the benchmark inputs:

```powershell
.\.venv\Scripts\python.exe -m dedup.cli generate --rows 2000 --seed 3 --out data/generated/phase7c_seed3_2000.csv --truth-out data/generated/phase7c_seed3_2000_truth.csv
.\.venv\Scripts\python.exe -m dedup.cli generate --rows 100000 --seed 3 --out data/generated/phase7c_seed3_100000.csv --truth-out data/generated/phase7c_seed3_100000_truth.csv
```

The 100K production run used a fresh SQLite file, called `init_schema`, then made one `run_pipeline(conn, [csv_path], config, as_of="2026-10-31T00:00:00Z")` call. It did not open the 100K truth file. Its run ID is `run_20261031T173844Z_e0c9` and status is `success`. The exact stage timing values are persisted in that run's `metrics_json` under `stage_timings`.

## 2,000-row naive-versus-blocked experiment

The 2K CSV alone was ingested into a temporary database and current valid source-record versions were loaded. Blocking was timed by itself. Then both the naive all-pairs path and blocked-candidate path called the same `dedup.scoring.score_pair` function with the same records, weights, and `last_name_min_jw`. For each blocked candidate, the feature object from naive scoring exactly equaled the feature object from blocked scoring. Ground truth was opened only after both scoring passes completed, solely to calculate true-pair blocking recall.

| Measurement | Naive all pairs | Blocked candidates |
|---|---:|---:|
| Scoring comparisons | 1,304,920 | 1,690 |
| Scoring wall time | 21.7041 s | 0.0291 s |

Blocking generation itself took **0.0113 s** and produced the 1,690 candidate pairs. Reduction ratio was **0.9987049 (99.8705%)**. The 2K truth set contained 522 true pairs: 499 were candidates and 23 were lost by blocking. True-pair blocking recall was **95.5939%**. No block was capped in this 2K experiment.

The naive scorer was actually run only for the 2K experiment. No 100K all-pairs scoring was run; its naive comparison count below is only `n*(n-1)/2`.

## Full 100,000-row pipeline

| Stage | Wall time |
|---|---:|
| Stage 1 ingest, validate, normalize | 218.151 s |
| Blocking | 4.264 s |
| Scoring and classification | 31.040 s |
| Clustering and transitive-conflict checks | 0.674 s |
| Survivorship and lineage | 175.971 s |
| Publishing | 13.711 s |
| Compute setup and assembly | 6.978 s |
| **Total `run_pipeline` wall time** | **450.995 s (7 min 30.995 s)** |

The largest measured stage was stage 1 at 218.151 seconds; survivorship and lineage took 175.971 seconds. Together they accounted for most of the run. The total remained below the plan's 10-minute profiling threshold, so no cProfile pass or hotspot change was made.

| Count or metric | Result |
|---|---:|
| Input rows | 100,000 |
| Valid rows | 86,000 |
| Rejected rows | 14,000 |
| Unique source records | 81,092 |
| Candidate pairs (auto-merge plus review) | 41,601 |
| Comparisons blocked and scored | 218,140 |
| Naive comparisons (`81,092 * 81,091 / 2`, arithmetic only) | 3,287,915,686 |
| Blocking reduction ratio | 0.9999336540 (99.9934%) |
| Golden records | 64,250 |
| Merged-away records | 16,842 |
| Review queue size | 21,831 |
| Capped blocks | 3 |
| Pairs skipped due to caps | 2,513,750 |
| SQLite database file size after close | 159,363,072 bytes |
| Python `tracemalloc` peak | 588,271,628 bytes (561.0 MiB) |
| Process sampled peak working set | 1,455,824,896 bytes (1.356 GiB) |

Largest capped blocks:

| Key | Size | Pairs skipped |
|---|---:|---:|
| email `accounts@example.org` | 1,334 | 889,111 |
| email `support@example.net` | 1,292 | 833,986 |
| email `info@example.com` | 1,258 | 790,653 |

## Reconciliation and correctness

The run status was `success`. Every publish reconciliation identity passed: input rows equaled rejects plus valid rows; rejects matched the sum by reason; 81,092 unique source records matched 64,250 golden records plus 16,842 merged-away records; the 81,092 golden-member rows matched unique source records; the merged-cluster aggregate reconciled to 13,732 multi-member golden records; lineage had zero orphans; and SQLite reported zero foreign-key violations.

Published counts were 64,250 `golden_customers`, 81,092 `golden_members`, 387,000 `golden_lineage`, 41,601 `candidate_pairs`, and 21,831 `review_queue`. Decision counts were 19,770 `auto_merge`, 21,831 `review`, and 176,539 `non_match`.

The observed input-generation optimization was checked for byte-identical CSV and truth output against the pre-optimization 2K seed-3 files. The existing seed-1/seed-2 datasets and prior reports were not overwritten. Ground truth was not supplied to either production pipeline run; only the 2K truth file was read after the comparison scoring completed.

The test suite passed after the timing and generator changes: **90 passed**. This includes the 3,000-record blocking comparison-count guard.
