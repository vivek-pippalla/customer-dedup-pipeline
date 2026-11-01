# ChatGPT planning prompts — recovered records

## Prompt 1 — Initial build-plan request

I need build plan for it so that I can feed it in antigravity models or use it to build the pipeline

and explain about core logic, key design choices(with options), dependencies, limitations, Assumptions, trade-offs, testing approach, how the solution may work

## Prompt 2 — Review the proposed nine-phase plan

what do you think of this

The 9 phases
Follow this order. Each phase has a completion condition.

Phase 0 — Project foundation Start here
Verify repository structure.
Confirm Python and Conda environment.
Set up dependencies.
Configure .gitignore.
Create README, checklist, and prompt-history folder. Deliverable: Clean, reproducible project skeleton.
Phase 1 — Database design and setup
Finalize SQLite schema.
Create database connection module.
Enable foreign keys.
Add constraints and indexes.
Create source systems and run log tables.
Implement deterministic ID helpers. Deliverable: Database initializes successfully with all required tables.
Phase 2 — Data generation and ingestion
Create realistic synthetic customer CSV data.
Create separate ground-truth labels.
Read CSV files.
Calculate source record identity and row hashes.
Store original records without losing raw values.
Handle duplicate deliveries safely. Deliverable: Customer records are stored correctly in SQLite.
Phase 3 — Validation and normalization
Validate required fields.
Validate email and timestamps.
Check source-system references.
Send invalid records to quarantine.
Normalize names, emails, phone numbers, and addresses.
Preserve original values. Deliverable: Valid normalized records and traceable rejected records.
Phase 4 — Candidate generation and matching
Implement multiple blocking strategies.
Generate unique candidate pairs.
Implement exact matching rules.
Implement fuzzy similarity.
Calculate weighted scores.
Apply hard-conflict checks.
Classify pairs as auto-merge, review, or non-match. Deliverable: Explainable matching decisions with reasons.
Phase 5 — Clustering and survivorship
Group confidently matched records.
Implement union-find.
Detect transitive conflicts.
Apply deterministic field-level survivorship.
Generate golden customer records.
Preserve field-level lineage and cluster membership. Deliverable: Golden records with traceable source information.
Phase 6 — Publishing and operational reliability
Publish golden records transactionally.
Maintain the review queue.
Implement run logging and error reporting.
Handle retries and failures.
Verify idempotency.
Preserve previous successful output if publishing fails. Deliverable: Reliable end-to-end pipeline execution.
Phase 7 — Testing, evaluation, and performance
Write unit and integration tests.
Test edge cases and conflicting identities.
Test shuffled input and repeated execution.
Calculate precision, recall, and F1.
Run reconciliation checks.
Benchmark blocking and pipeline execution. Deliverable: Actual test results, metrics, and evidence.
Phase 8 — Submission preparation
Complete README and architecture documentation.
Document assumptions, limitations, and trade-offs.
Prepare AI usage disclosure and prompt history.
Verify Git history.
Test from a clean clone and environment.
Publish the public GitHub repository. Deliverable: Reproducible, understandable submission.


## Prompt 3: Important changes before coding (A–F)


I have some suggestions

Important changes I'd make before coding\
&#x20;A. Scoring can produce dangerous false positives\
&#x20;The plan says missing features are excluded and the remaining weights are renormalized.

That sounds reasonable, but consider this example:\
&#x20;Field	Record A	Record B\
&#x20;Email	john@gmail.com	john@gmail.com\
&#x20;Phone	Missing	Missing\
&#x20;Name	John Smith	Different Person\
&#x20;DOB	Missing	Missing

If email is the only available matching feature, renormalization can make the score 1.0. That is not sufficient evidence to auto-merge.

My recommendation: Add minimum evidence requirements independently of the score.

For example:

- Email-only match → review, never automatic merge.
- Phone-only match → review, never automatic merge.
- Name-only similarity → never automatic merge.
- Strong identifier plus compatible name → potentially auto-merge.
- Conflicting DOB → never auto-merge.
- Shared email/phone with different canonical first names → review.\
  &#x20;The score should rank the evidence; the guard rails should decide whether that evidence is sufficient.\
  &#x20;B. The golden ID strategy has a limitation\
  &#x20;The plan proposes:

golden_id = hash(sorted member source_record_ids)

This is deterministic, but when a new record joins an existing cluster, the membership changes and so does the golden ID.

For a demonstration, this is acceptable. For a production customer master, it can cause problems for downstream systems referencing the old ID.

I recommend documenting this as a deliberate limitation and adding a golden_id_history or golden_id_aliases table if time permits.\
&#x20;C. Raw record identity and idempotency need clarification\
&#x20;The document defines:

source_record_id = hash(source_system + source_native_id)

But it also proposes inserting raw records using row_hash.

These represent different concepts:

- source_record_id: identity of a logical customer record from a source.
- row_hash: fingerprint of the contents of a particular version of that record.
- run_id: identity of a pipeline execution.\
  &#x20;A source might update the same customer record several times. If you treat the source record ID as the unique raw-record key, you risk losing legitimate updates.

Better design: Keep source record identity separate from source record versions or events. Use a unique key for each source event/version, preserve the original content, and make ingestion idempotent against that key.\
&#x20;D. Don't erase human review decisions during publishing\
&#x20;The plan says to delete and recreate the review queue during every full recomputation.

That works for a basic demonstration, but it becomes problematic when a reviewer has already resolved a pair. The next run could erase that decision.

Keep these concepts separate:

- Generated review candidates for a particular run.
- Human review decisions and their history.\
  &#x20;At minimum, document that review decisions are not persistent yet. Ideally, preserve them in a separate table.\
  &#x20;E. Reconciliation needs a precise definition\
  &#x20;The document proposes:

rows_in = rejected + merged_away + golden_survivors

This is useful, but only if all three categories are measured over the same input batch and the definitions are unambiguous.

I'd report at least:

- Input rows.
- Invalid/rejected rows.
- Valid records.
- Unique source records.
- Records assigned to golden clusters.
- Records merged away.
- Golden records produced.
- Records pending review.\
  &#x20;Also, a record pending review is not necessarily a non-match. Make sure it is not counted as a successfully merged record.\
  &#x20;F. A few smaller corrections\
  &#x20;Item	My recommendation\
  &#x20;Python 3.11	Python 3.12 is fine too; use the version already established in your environment\
  &#x20;rapidfuzz	Good choice for speed, but pin the dependency and explain that matching logic is your own\
  &#x20;Future timestamps	Rejecting all future timestamps can be too strict; use a documented tolerance or quarantine policy\
  &#x20;Block cap of 200	Log oversized blocks and quantify the resulting potential recall loss\
  &#x20;Nickname mapping	Keep it small, explicit, tested, and avoid assuming every nickname is interchangeable\
  &#x20;Transitive conflicts	Test entire clusters, not just individual pairs\
  &#x20;INSERT OR IGNORE	Use only with a clearly defined uniqueness constraint; otherwise it can hide unexpected data problems

4. My recommended final technology stack\
   &#x20;Component	Decision\
   &#x20;Language	Python 3.12\
   &#x20;Environment	Your existing Conda dedup environment\
   &#x20;Database	SQLite\
   &#x20;CSV processing	Python standard library\
   &#x20;Fuzzy matching	RapidFuzz\
   &#x20;Testing	pytest\
   &#x20;Synthetic data	Python generator; Faker optional\
   &#x20;Configuration	TOML\
   &#x20;Version control	Git

You don't need to switch to uv just because the document uses it. Your existing Conda environment is perfectly suitable. Keep the dependency installation and setup instructions reproducible.


## Additional planning requirements recovered from conversation history

I also asked for the build plan to cover:

- Business Context
- Objective and Scope
- Actors
- Workflow
- IDs
- Granular implementation steps
- Volume
- Edge cases
- Acceptance criteria
- Evaluation
- Deliverables

**Recovery note:** The exact original wording of this additional request is not available in the recovered conversation context. This is a summary, not a reconstructed original prompt.
