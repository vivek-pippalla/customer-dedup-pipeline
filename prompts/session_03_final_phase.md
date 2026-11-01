# dedup final phase


> Task: write README.md. Read BUILD_PLAN fully and the actual code, reports/ and tests/. Follow the standing rules. Everything you state must match the code and the saved reports; where the plan and the code disagree, tell me instead of choosing.
> Sections: one-paragraph summary; quick start (conda: conda env create -f environment.yml or conda activate dedup + pip install -e .; plain venv alternative; Windows-safe commands); how to run on the sample, how to generate data, how to evaluate, how to report; architecture and flow (ASCII diagram); stages and transactions; data dictionary (link docs/DATA_DICTIONARY.md and show a grain/key summary table) with an ASCII entity-relationship diagram; naming conventions (snake_case, ID formulas, ISO-8601, run_id/source_file fields); definitions (exact, probable, review, version, current version); matching and evidence gates (the decision table); survivorship rules (the chain table) and lineage; reconciliation identities with a real example from reports/reconciliation.md; operational behaviour: idempotency, retry, restart, backfill (late data), what happens on crash; testing (how to run, what each layer covers, link to reports/pytest_output.txt); evaluation and performance results (copy real numbers from reports only); assumptions (use the A-numbers in BUILD_PLAN section 15, corrected to match the code); key decisions and trade-offs (short, link DESIGN_NOTES.md); a 'How I know it works' table mapping each of the 9 edge cases and 7 acceptance criteria to a test, report or query; limitations and next steps; a synthetic-data notice; AI usage pointer (AI_USAGE.md); project layout. Keep it scannable. No marketing language. Do not claim anything that has no test or report behind it.




> 1. Update the test evidence to 91 passed in 1.79s.
> 2. Remove the outdated 89/90-pass ambiguity.
> 3. Keep the clean-clone verification gap clearly documented.
> 4. Leave `AI_USAGE.md` TODOs for the next documentation task rather than inventing your personal verification history.
> 5. I independently ran the full test suite using `.venv\Scripts\python.exe -m pytest -p no:cacheprovider --basetemp=test-temp`. All 91 tests passed in 1.79 seconds on Python 3.11.18. Update README.md with this verified result and remove the outdated 89/90-pass discrepancy.


>  Phase 8B — Design notes, checklist and AI usage
>
> Task: Write `DESIGN_NOTES.md`, complete `CHECKLIST.md`, and draft `AI_USAGE.md`. Follow the standing project rules and read `docs/BUILD_PLAN.md`, the actual implementation, tests, reports, prompts and existing documentation before editing.
>
>  1. DESIGN_NOTES.md
>
> Use Build Plan section 15:
> Assumptions A1–A12.
> Decisions D1–D11.
> Trade-offs.
> Testing approach.
> How I know it works.
>
> Also expand the decision table in section 4 into short paragraphs explaining:
> Options considered.
> Why the implemented option was chosen.
> What the decision costs or limits.
>
> Correct statements that no longer match the implementation. Include additional implementation decisions made during development, using the actual prompts and project notes as evidence.
>
> Explicitly document these limitations:
> Nickname map and address abbreviations are small and India/English focused.
> No transliteration handling.
> Weights are hand-tuned using synthetic data.
> Golden IDs change when cluster membership changes; golden ID history is not implemented.
> Review decisions persist but are not applied to clustering.
> Capped blocks can lose recall. Include measured figures from the performance report.
> SQLite supports one writer at a time.
> The pipeline is batch-only.
> Evaluation and performance measurements use synthetic data and do not establish production accuracy.
>
> Do not add unsupported claims or present planned features as implemented.
>
> 2. CHECKLIST.md
>
> Complete all 9 required edge cases and all 7 acceptance criteria from the Build Plan.
>
> For each item:
> Mark complete only when implementation and supporting evidence exist.
> Include an exact test name, report path, or SQL query as evidence.
> Mark incomplete items explicitly as NOT DONE.
> Do not infer completion from a related test if the actual requirement is not covered.
>
> Important status distinctions:
> Automated shuffle/reversed-file tests are covered by their named test.
> Seed 2 was generated but its independent evaluation was not completed. Mark that evaluation as NOT DONE.
> Manual inspection of 20 review-queue records and tracing a cluster by hand must remain NOT DONE until I personally complete them.
> Clean-clone verification is still pending. Do not mark it complete.
>
> Use the latest verified test result: **91 passed in 1.79s on Python 3.11.18**.
>
>  3. AI_USAGE.md
>
> Draft the structure only. Leave explicit TODO placeholders for me to complete.
>
> Include sections for:
> AI tools and models used.
> Where AI generated most of the work (boilerplate, generator, tests, etc.).
> What I rewrote, reviewed or decided myself.
> What I personally verified.
>
> Under personal verification, provide a checklist of possible activities, including:
> Shuffle/reversed-file verification.
> Inspecting 20 review-queue items.
> Tracing one golden cluster through its lineage.
> Comparing reconciliation figures against SQL query results.
> Reviewing benchmark results and limitations.
>
> Do not claim that I personally performed any of these activities unless I explicitly confirm them. Automated test evidence must be distinguished from manual verification.
>
>  4. Final review
>
> After editing:
> Check every factual statement against code, tests or reports.
> Keep the three documents consistent with README.md.
> Preserve existing project decisions and terminology.
> Do not modify application code or add features.
> Do not run tests unnecessarily for documentation-only changes.
> Run `git diff --check`.
> Show me a summary of files changed, checklist items still incomplete, and every TODO I must personally fill.
> Do not commit anything yet.



> Task: help me verify a clean clone. Give me a numbered checklist of commands (Windows-friendly) to: clone the public repo into a new empty folder; create a brand-new conda env named dedup-clean from environment.yml; activate it; run the README quick-start commands verbatim; run the sample pipeline; run pytest; run a 2,000-row generate + run + evaluate; and diff the produced sample output against data/sample/output/. For every step state the expected result. Then I will run it and paste any failure back to you. Do not skip steps and do not assume files exist that are not committed.



> We have completed Phase 8C clean-room verification. Update the documentation only; do not modify application code, tests, configuration, generated outputs, or database files.
>
> Read the current README.md, CHECKLIST.md, AI_USAGE.md, DESIGN_NOTES.md, reports/pytest_output.txt, and prompts/ directory before editing.
>
> Use these verified facts:
>
> **Clean clone**
>
> - Public repository cloned into `D:\PROJECTS\TESTING_DEDUP\customer-dedup-pipeline`.
> - Clean clone was at commit `0d8a73e`.
> - Fresh Conda environment `dedup-clean`.
> - Python 3.11.18.
> - `python -m pip install -e .` succeeded.
> - `python -m pip install -e ".[dev]"` installed development/test dependencies.
> - `python -m dedup.cli --help` listed all six commands.
> - Sample pipeline completed successfully: 50 input, 7 rejected, 43 valid, 41 unique source records, 32 golden records, 9 merged-away records, 2 pending review pairs.
> - `python -m pytest -p no:cacheprovider --basetemp=test-temp` completed with **91 passed in 1.80s**.
> - Generated a 2,000-row seed-3 dataset, ran the pipeline, and evaluated it successfully.
> - All four clean-clone sample CSV exports matched the committed reference files byte-for-byte using `fc /b`: golden_customers.csv, golden_lineage.csv, rejects.csv, review_queue.csv.
>
> **Required edits**
>
> 1. README.md: add a concise "Clean-clone verification" section. Document the clean environment, test result, sample workflow, and byte-identical CSV comparison. Mention that tests require `python -m pip install -e ".[dev]"`; base installation alone does not install the optional pytest dependency.
> 2. CHECKLIST.md: mark clean-clone verification DONE and cite the exact evidence above. Keep independent seed-2 evaluation, manual inspection of 20 review items, and manual lineage tracing NOT DONE until actually performed.
> 3. AI_USAGE.md: replace only the clean-clone verification TODO with the verified facts above. Do not claim manual review, manual lineage tracing, or other checks that have not been performed. Keep remaining personal-verification TODOs.
> 4. reports/pytest_output.txt: inspect whether it contains multiple historical test runs. Make it a clean record of the latest full-suite run only, if the exact latest output is available. Do not fabricate or reconstruct console output. If unavailable, leave it unchanged and report that.
> 5. DESIGN_NOTES.md: do not rewrite it unnecessarily. Correct only demonstrable inaccuracies.
>
> **Prompt archive**
> Inspect prompts/ and list missing session records. Do not invent exact historical prompts or pretend the archive is complete. If exact prompts cannot be recovered, record the gap honestly in AI_USAGE.md or prompts/README.md.
>
> After editing:
>
> - Show `git diff --check`.
> - Show `git status --short`.
> - Summarize every changed file and any remaining TODO.
> - Do not commit or push.
> - Do not mark seed-2 evaluation or manual checks complete.
