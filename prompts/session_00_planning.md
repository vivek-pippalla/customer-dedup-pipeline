# Session 00 — Initial Project Brief and Planning

## Project Context

The project is `customer-dedup-pipeline`: a Python data-engineering project for customer duplicate detection, using SQLite and pytest. It was developed as part of a 72-hour hiring challenge.

The authoritative design document is `docs/BUILD_PLAN.md`.

## Initial Project Instructions

You are helping me build "customer-dedup-pipeline": a Python data-engineering project (customer duplicate detection, SQLite, pytest) for a 72-hour hiring challenge. The authoritative design is docs/BUILD_PLAN.md in this repo. Read the sections I name before coding and follow them exactly. If the plan is ambiguous or contradicts itself, stop and ask me instead of guessing.

Environment: conda env "dedup" (Python 3.11 or newer; the exact version is whatever `python --version` reports inside that env), package at src/dedup installed with `pip install -e .`. Run tests with `python -m pytest`. Use pathlib, open files with encoding="utf-8" and newline="" for CSV, and no shell-specific code in the package (I may be on Windows).

### Standing Rules

1. Standard library + rapidfuzz only inside src/dedup. No pandas, no recordlinkage/dedupe or any library that does matching for me. Matching, scoring, clustering and survivorship must be our own code.
2. snake_case everywhere. ISO-8601 UTC timestamps. Deterministic IDs exactly as in BUILD_PLAN section 3.4 (sha1, no uuid4, no timestamps or run_id inside data IDs).
3. Output must not depend on input row order or on dict/set iteration order: sort before iterating, and break ties with the smallest source_record_id.
4. No hardcoded paths, thresholds or weights. Read config/default.toml; CLI flags override it.
5. Any SQL insert that can conflict uses an explicit ON CONFLICT (...) target. Never bare INSERT OR IGNORE.
6. Small single-purpose functions with type hints and short docstrings. Keep modules focused (under about 300 lines).
7. Write the tests together with the code, in the same step. Run the full suite and show me the real output. Never invent or estimate counts, metrics or timings. If you did not run it, say so.
8. Do not touch files outside the scope of the task. Do not commit; I commit.
9. At the end give me: files changed, decisions you made that the plan did not specify, anything not finished, and the exact commands you ran.
10. Ground-truth files are read only by evaluate.py, scripts/ and tests. The `run` pipeline must never accept or read them.
11. Use the stdlib logging module (logging.getLogger(__name__)) in library modules; only cli.py prints. All data is synthetic: no real people, companies, secrets or credentials in code, tests or data.

## Archive Note

The implementation-phase prompts are recorded chronologically in the subsequent session files. This file preserves the initial project brief and standing instructions.