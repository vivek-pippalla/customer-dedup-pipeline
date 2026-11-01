# dedup project phase 0,1,2


> You are helping me build "customer-dedup-pipeline": a Python data-engineering project (customer duplicate detection, SQLite, pytest) for a 72-hour hiring challenge. The authoritative design is docs/BUILD_PLAN.md in this repo. Read the sections I name before coding and follow them exactly. If the plan is ambiguous or contradicts itself, stop and ask me instead of guessing.
> Environment: conda env "dedup" (Python 3.11 or newer; the exact version is whatever `python --version` reports inside that env), package at src/dedup installed with `pip install -e .`. Run tests with `python -m pytest`. Use pathlib, open files with encoding="utf-8" and newline="" for CSV, and no shell-specific code in the package (I may be on Windows).
> Rules:
> 1. Standard library + rapidfuzz only inside src/dedup. No pandas, no recordlinkage/dedupe or any library that does matching for me. Matching, scoring, clustering and survivorship must be our own code.
> 2. snake_case everywhere. ISO-8601 UTC timestamps. Deterministic IDs exactly as in BUILD_PLAN section 3.4 (sha1, no uuid4, no timestamps or run_id inside data IDs).
> 3. Output must not depend on input row order or on dict/set iteration order: sort before iterating, and break ties with the smallest source_record_id.
> 4. No hardcoded paths, thresholds or weights. Read config/default.toml; CLI flags override it.
> 5. Any SQL insert that can conflict uses an explicit ON CONFLICT (...) target. Never bare INSERT OR IGNORE.
> 6. Small single-purpose functions with type hints and short docstrings. Keep modules focused (under about 300 lines).
> 7. Write the tests together with the code, in the same step. Run the full suite and show me the real output. Never invent or estimate counts, metrics or timings. If you did not run it, say so.
> 8. Do not touch files outside the scope of the task. Do not commit; I commit.
> 9. At the end give me: files changed, decisions you made that the plan did not specify, anything not finished, and the exact commands you ran.
> 10. Ground-truth files are read only by evaluate.py, scripts/ and tests. The `run` pipeline must never accept or read them.
> 11. Use the stdlib logging module (logging.getLogger(__name__)) in library modules; only cli.py prints. All data is synthetic: no real people, companies, secrets or credentials in code, tests or data.



> Task: finish Phase 0 (project foundation). Follow the standing rules.
>
> Already committed: .gitignore, environment.yml, pyproject.toml, README.md, requirements.txt. First READ all five and tell me, as a short list, what is wrong or missing against the checklist below. Then make minimal edits. Do not overwrite README.md content; add headings only.
>
> Checklist:
> a) pyproject.toml: setuptools backend, src layout (package "dedup" in src/dedup), requires-python >= 3.11, dependency rapidfuzz, optional dev dependency pytest, [tool.pytest.ini_options] with testpaths = ["tests"], console script dedup = "dedup.cli:main".
> b) requirements.txt: pinned (==) rapidfuzz and pytest. Read the installed versions with `pip list`; do not guess versions. Remove faker if present (the generator will not use it).
> c) environment.yml: name dedup, the same python minor version as my env, pip section containing "-e ." .
> d) .gitignore must ignore: out/, *.db, *.db-wal, *.db-shm, data/generated/, __pycache__/, .pytest_cache/, *.egg-info/, .vscode/ . It must NOT ignore data/sample/ or reports/.
> e) Create folders and empty-but-importable modules exactly as in BUILD_PLAN section 6 (each with a one-line module docstring). Create config/default.toml (copy from section 6) and config/nicknames.toml (small explicit map from section 3.2, as a TOML table). Create CHECKLIST.md (the 9 required edge cases and 7 acceptance criteria from the problem statement as unchecked boxes with an Evidence column), prompts/README.md, prompts/session_00_planning.md (a stub with a TODO; I will paste my own planning prompts), AI_USAGE.md and DESIGN_NOTES.md skeletons.
> f) src/dedup/config.py: load TOML with tomllib, validate that weights sum to 1.0 (tolerance 1e-9), thresholds satisfy 0 < review < auto <= 1, and source_priority is non-empty. Raise a clear ConfigError otherwise.
> g) cli.py with argparse subcommands init-db, run, generate, evaluate, report (stubs that print "not implemented yet" and exit 2) and a main() function.
> h) tests/test_smoke.py and tests/test_config.py covering: package imports, default config loads, bad weights rejected, bad thresholds rejected.
>
> Done when: `pip install -e .` works, `python -m pytest` passes, and `python -m dedup.cli --help` lists the five subcommands.



> conda info --envs
> python --version
> python -m pip list



> Task: finish Phase 0 (project foundation). Follow the standing rules.
>
> Already committed: .gitignore, environment.yml, pyproject.toml, README.md, requirements.txt. First READ all five and tell me, as a short list, what is wrong or missing against the checklist below. Then make minimal edits. Do not overwrite README.md content; add headings only.
>
> Checklist:
> a) pyproject.toml: setuptools backend, src layout (package "dedup" in src/dedup), requires-python >= 3.11, dependency rapidfuzz, optional dev dependency pytest, [tool.pytest.ini_options] with testpaths = ["tests"], console script dedup = "dedup.cli:main".
> b) requirements.txt: pinned (==) rapidfuzz and pytest. Read the installed versions with `pip list`; do not guess versions. Remove faker if present (the generator will not use it).
> c) environment.yml: name dedup, the same python minor version as my env, pip section containing "-e ." .
> d) .gitignore must ignore: out/, *.db, *.db-wal, *.db-shm, data/generated/, __pycache__/, .pytest_cache/, *.egg-info/, .vscode/ . It must NOT ignore data/sample/ or reports/.
> e) Create folders and empty-but-importable modules exactly as in BUILD_PLAN section 6 (each with a one-line module docstring). Create config/default.toml (copy from section 6) and config/nicknames.toml (small explicit map from section 3.2, as a TOML table). Create CHECKLIST.md (the 9 required edge cases and 7 acceptance criteria from the problem statement as unchecked boxes with an Evidence column), prompts/README.md, prompts/session_00_planning.md (a stub with a TODO; I will paste my own planning prompts), AI_USAGE.md and DESIGN_NOTES.md skeletons.
> f) src/dedup/config.py: load TOML with tomllib, validate that weights sum to 1.0 (tolerance 1e-9), thresholds satisfy 0 < review < auto <= 1, and source_priority is non-empty. Raise a clear ConfigError otherwise.
> g) cli.py with argparse subcommands init-db, run, generate, evaluate, report (stubs that print "not implemented yet" and exit 2) and a main() function.
> h) tests/test_smoke.py and tests/test_config.py covering: package imports, default config loads, bad weights rejected, bad thresholds rejected.
>
> Done when: `pip install -e .` works, `python -m pytest` passes, and `python -m dedup.cli --help` lists the five subcommands.




> Task: Phase 1. Read BUILD_PLAN sections 3.3, 3.4, 5 and 9 first. Follow the standing rules.
> Build:
> 1. src/dedup/schema.sql with every table in section 5: primary keys, foreign keys, NOT NULL where stated, CHECK constraints (runs.status, review_decisions.decision, candidate_pairs.decision, review_queue.status), UNIQUE constraints as stated, and indexes on raw_customer_records(source_record_id), clean_customers(source_record_id), golden_members(source_record_id), candidate_pairs(source_record_id_a), candidate_pairs(source_record_id_b).
> 2. src/dedup/db.py: connect(path) that creates parent folders, sets PRAGMA foreign_keys=ON, journal_mode=WAL (skip WAL for ":memory:"), isolation_level=None (we manage transactions explicitly), row_factory=sqlite3.Row; init_schema(conn) that applies schema.sql idempotently and seeds source_systems from config.source_priority; a transaction() context manager that issues BEGIN IMMEDIATE, then COMMIT or ROLLBACK on exception.
> 3. src/dedup/ids.py: source_record_id, row_hash, version_id, golden_id, pair_id, new_run_id exactly as section 3.4. new_run_id takes an optional clock and suffix so tests can make it deterministic. Also normalize_source_key helpers (trim + upper for source_system, trim for native id).
> 4. src/dedup/runlog.py: start_run(conn, ...) inserts status "running" and commits immediately; finish_run(conn, run_id, status, counts, metrics, error) updates and commits; mark_abandoned_runs(conn) marks any leftover "running" rows as "failed" with error "abandoned: process stopped before finishing" (called at the start of each run).
> 5. Add configure_logging(level) to runlog.py (stdlib logging, one console handler, ISO-8601 timestamps) and call it from cli.py using --log-level or config [logging].
> 6. Wire `dedup init-db --db PATH` to create the database.
> 7. scripts/gen_data_dictionary.py: read the live schema (PRAGMA table_info and foreign_key_list) from a fresh in-memory database and write docs/DATA_DICTIONARY.md with one table per database table: column, SQLite type, nullable, primary/foreign key, source-or-derived, and a one-line description. Keep the descriptions in a dict inside the script and exit non-zero if any table or column has no description, so the dictionary cannot drift from schema.sql. Put the grain of each table and the assumptions A1-A12 from BUILD_PLAN section 15 at the top (copy them; do not invent new ones).
> Tests (tests/test_db.py, test_ids.py, test_runlog.py): schema applies twice without error; foreign keys are enforced (inserting a raw row with unknown source_system fails); CHECK constraints reject bad status values; transaction() rolls back on exception; every ID function is deterministic and has golden values hard-coded in the test (compute them once and paste them in, so accidental changes are caught); pair_id is symmetric; source_record_id ignores case and surrounding spaces in source_system; version_id changes when content changes but source_record_id does not; run log row survives a rolled-back data transaction; mark_abandoned_runs works; the data-dictionary script fails when a column description is missing and succeeds on the real schema.
> Done when: `python -m dedup.cli init-db --db out/test.db` creates all tables, docs/DATA_DICTIONARY.md is generated, and the test suite passes.



> Task: Phase 2A, the synthetic data generator. Read BUILD_PLAN sections 3.3, 3.4 and 3.12. Follow the standing rules.
>
> Implement src/dedup/generate.py and wire `dedup generate` with args: --rows, --seed, --dup-rate, --family-rate, --invalid-rate, --late-rate, --batches (default 1), --out, --truth-out. Use only random.Random(seed) and our own word lists (put the lists in src/dedup/wordlists.py, about 60 first names incl. nickname pairs, 60 last names, 20 cities with 6-digit postcodes, 20 street names). No Faker, no global random state, no time-based values.
>
> Behaviour per section 3.12: --rows is the exact number of CSV data rows emitted (invalid rows included); entities emit 1-4 records across CRM/WEB/IMPORT with noise (case, whitespace, typos, nickname swaps, missing fields, formatted phones, address abbreviations); family members (different entities) share an email or phone; a few shared role mailboxes (e.g. info@example.com) are used by many entities; late versions (same source_native_id with an older updated_at positioned after the newer one, or in a later batch file); boundary values (1-character name, 300-character address, empty strings); and labelled invalid rows (bad email, empty name, unknown source system, wrong column count, unparseable timestamp, far-future timestamp, same key + same timestamp with different content).
>
> CSV columns: source_system, source_native_id, full_name, email, phone, address, postcode, dob, updated_at. Write ground_truth.csv separately with columns: source_file, row_number, source_record_id (blank if it cannot be computed; use dedup.ids), true_entity_id, is_invalid, expected_reject_reason (blank if valid), injected_issue. For the same-key-same-timestamp-different-content injection, compute row_hash with dedup.ids and mark the row with the LARGER row_hash as the invalid one (reason duplicate_key), because the validator keeps the smallest. Use fixed date ranges (valid updated_at between 2023-01-01 and 2025-12-31; far-future rows in 2099) and never the wall clock. Use only reserved or invented email domains (example.com, example.org, example.net, mail.invalid). Also write a manifest JSON beside the output with all arguments and the seed. If --batches K > 1, write K files named <out stem>_batch1.csv ... and put late versions in later batches.
>
> Tests (tests/test_generate.py): same args produce byte-identical output (compare file hashes); different seeds differ; --rows is exact; the ground truth has one line per emitted data row; invalid rows exist when invalid-rate > 0 and each has an injected_issue; at least one family pair and one late version exist in a 500-row run; the generated file's header matches the expected schema; each duplicate_key pair labels exactly one row invalid and it is the one with the larger row_hash; every valid updated_at is inside the fixed range.
>
> Then run: python -m dedup.cli generate --rows 50 --seed 42 --out data/sample/customers_sample.csv --truth-out data/sample/ground_truth_sample.csv and show me the first 15 rows so I can eyeball realism. Do not commit.



> Task: Phase 2B, ingestion. Read BUILD_PLAN sections 3.3 and 3.4. Follow the standing rules.
> Implement src/dedup/ingest.py (no validation rules yet; validation is Phase 3):
> 1. read_batch(path) -> BatchRead with: file_error (None or a string), warnings (list, e.g. extra columns), rows (list of RawRow with source_file basename, source_row_number starting at 1 for the first data row, raw_line text, and the field dict), structural_rejects (rows with the wrong column count, reason malformed_row, with raw_line preserved). Zero-byte file or header-only file -> BatchRead with empty rows and a flag is_empty. A missing or renamed required column -> file_error naming the missing columns. Extra columns -> ignored, warning recorded. Use the csv module; open with encoding utf-8-sig and newline="". Never crash on a bad row.
> 2. compute_keys(row) -> adds source_record_id, row_hash, version_id (via ids.py) for rows that have usable source_system and source_native_id.
> 3. insert_versions(conn, rows, run_id) -> (inserted_count, duplicate_event_count). Use INSERT ... ON CONFLICT (version_id) DO NOTHING and derive the counts from cursor.rowcount; do not pre-check with SELECT. Raw values are stored exactly as read (no trimming or case changes). The function assumes rows are already valid and must run inside a caller-provided transaction.
> Tests (tests/test_ingest.py) using tmp_path and hand-written CSV text: happy path; header-only file; zero-byte file; missing required column gives a file_error naming it; extra column gives a warning and rows still read; wrong column count row becomes a malformed_row reject while other rows continue; quoted commas and embedded newlines parse correctly; non-ASCII names survive; inserting the same rows twice gives inserted=N then inserted=0 and duplicates=N; the same source_record_id with different content inserts a second version; raw values are byte-for-byte preserved (leading spaces and upper case kept).
> Do not wire the CLI run command yet.



> **How should ingestion handle a valid but noncanonical source_system such as crm, given the raw value must be preserved but the current FK targets uppercase keys?**
>
> Preserve raw value and add a canonical FK key/alias design (Recommended)
