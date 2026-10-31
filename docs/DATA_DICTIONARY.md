# Data dictionary

## Table grains

- **candidate_pairs**: one auto_merge or review pair in the current computation
- **clean_customers**: one normalized valid version
- **golden_customers**: one real-world customer
- **golden_lineage**: one field of one golden record
- **golden_members**: one source record in one golden record
- **raw_customer_records**: one delivered version of one source record
- **rejects**: one rejected input row
- **review_decisions**: one human decision (never deleted)
- **review_queue**: one uncertain pair in the current computation (regenerated each run)
- **runs**: one pipeline execution
- **source_systems**: one source system

## Assumptions

| ID | Assumption | If it is wrong |
|---|---|---|
| A1 | The entity is customers and all data is synthetic | Metrics do not transfer to real data |
| A2 | Email and phone are strong but not unique per person (families, role mailboxes) | Handled by `shared_identifier_conflict` and the block cap |
| A3 | `(source_system, source_native_id)` identifies one logical record; a re-delivery with changed content is an update | If a source reuses native IDs, unrelated people merge |
| A4 | `updated_at` is the business time of a version; naive timestamps are UTC | Wrong current version if sources use local time |
| A5 | Phones are Indian 10-digit numbers (+91 and leading 0 handled); an invalid phone becomes NULL and the row is kept | International numbers lose the phone feature |
| A6 | Source priority is CRM > WEB > IMPORT (config) | Different winners when values tie on other rules |
| A7 | A wrong merge costs more than a missed duplicate | Thresholds favour precision; the review queue grows |
| A8 | File basenames are unique per ingested file | Reject idempotency key could collide |
| A9 | DOB, when present on both records, is reliable enough to block auto-merge; but entry errors exist, so a mismatch with a strong identifier goes to review | Some true duplicates wait for a human |
| A10 | Full recompute is affordable up to the benchmarked size (100k rows) | Needs an incremental design beyond that |
| A11 | One writer at a time (SQLite) | No concurrent runs |
| A12 | Ground truth is the generator's entity ids, the only notion of "true duplicate" available | Metrics reflect the generator's noise model |

## `candidate_pairs`

**Grain:** one auto_merge or review pair in the current computation.

| Column | SQLite type | Nullable | Key | Source or derived | Description |
|---|---|---|---|---|---|
| `pair_id` | TEXT | no | PK | derived | Deterministic identity of the unordered source-record pair. |
| `source_record_id_a` | TEXT | no | — | derived | Smaller source record ID in the pair. |
| `source_record_id_b` | TEXT | no | — | derived | Larger source record ID in the pair. |
| `email_score` | REAL | yes | — | derived | Email feature score, when present. |
| `phone_score` | REAL | yes | — | derived | Phone feature score, when present. |
| `name_score` | REAL | yes | — | derived | Name feature score, when present. |
| `address_score` | REAL | yes | — | derived | Address feature score, when present. |
| `dob_score` | REAL | yes | — | derived | DOB feature score, when present. |
| `score` | REAL | no | — | derived | Weighted pair score after missing-feature renormalization. |
| `coverage` | REAL | no | — | derived | Fraction of configured weight represented by shared features. |
| `decision` | TEXT | no | — | derived | Classification decision retained for this pair. |
| `reason_code` | TEXT | no | — | derived | Reason for the classification. |
| `match_tier` | TEXT | yes | — | derived | Exact or probable auto-merge tier, otherwise NULL. |
| `run_id` | TEXT | no | FK → `runs.run_id` | derived | Run that computed the pair. |

## `clean_customers`

**Grain:** one normalized valid version.

| Column | SQLite type | Nullable | Key | Source or derived | Description |
|---|---|---|---|---|---|
| `version_id` | TEXT | no | PK, FK → `raw_customer_records.version_id` | derived | Version identity shared with the raw record. |
| `source_record_id` | TEXT | no | — | derived | Stable identity of the logical source record. |
| `email_norm` | TEXT | yes | — | derived | Trimmed lowercase email. |
| `phone_norm` | TEXT | yes | — | derived | Normalized valid ten-digit phone, otherwise NULL. |
| `name_norm` | TEXT | yes | — | derived | Normalized full name. |
| `first_name_canon` | TEXT | yes | — | derived | First name after the explicit nickname lookup. |
| `first_is_initial` | INTEGER | yes | — | derived | Whether the canonical first name is one character (0 or 1). |
| `last_name_norm` | TEXT | yes | — | derived | Normalized last name. |
| `address_norm` | TEXT | yes | — | derived | Normalized address. |
| `postcode_norm` | TEXT | yes | — | derived | Normalized six-digit postcode, otherwise NULL. |
| `updated_at_utc` | TEXT | yes | — | derived | Source update timestamp normalized to UTC. |
| `dob_norm` | TEXT | yes | — | derived | ISO date of birth, otherwise NULL. |
| `soundex_last` | TEXT | yes | — | derived | Hand-computed Soundex of the normalized last name. |

## `golden_customers`

**Grain:** one real-world customer.

| Column | SQLite type | Nullable | Key | Source or derived | Description |
|---|---|---|---|---|---|
| `golden_id` | TEXT | no | PK | derived | Deterministic identity derived from sorted cluster members. |
| `full_name` | TEXT | yes | — | derived | Surviving customer name. |
| `email` | TEXT | yes | — | derived | Surviving email. |
| `phone` | TEXT | yes | — | derived | Surviving phone. |
| `address` | TEXT | yes | — | derived | Surviving address. |
| `postcode` | TEXT | yes | — | derived | Surviving postcode. |
| `dob` | TEXT | yes | — | derived | Surviving date of birth. |
| `member_count` | INTEGER | no | — | derived | Number of source records in the cluster. |
| `match_tier` | TEXT | no | — | derived | Cluster summary tier. |
| `latest_updated_at_utc` | TEXT | yes | — | derived | Latest member update timestamp. |
| `run_id` | TEXT | no | FK → `runs.run_id` | derived | Run that published this record. |

## `golden_lineage`

**Grain:** one field of one golden record.

| Column | SQLite type | Nullable | Key | Source or derived | Description |
|---|---|---|---|---|---|
| `golden_id` | TEXT | no | PK (1), FK → `golden_customers.golden_id` | derived | Golden record whose field is described. |
| `field_name` | TEXT | no | PK (2) | derived | Name of the survived field. |
| `value` | TEXT | yes | — | derived | Surviving field value, or NULL when absent. |
| `version_id` | TEXT | yes | FK → `raw_customer_records.version_id` | derived | Version that supplied the value. |
| `source_record_id` | TEXT | yes | — | derived | Source record that supplied the value. |
| `source_system` | TEXT | yes | FK → `source_systems.source_system` | derived | Source system that supplied the value. |
| `rule_applied` | TEXT | no | — | derived | Survivorship rule that selected the value. |
| `run_id` | TEXT | no | FK → `runs.run_id` | derived | Run that produced this lineage. |

## `golden_members`

**Grain:** one source record in one golden record.

| Column | SQLite type | Nullable | Key | Source or derived | Description |
|---|---|---|---|---|---|
| `golden_id` | TEXT | no | PK (1), FK → `golden_customers.golden_id` | derived | Golden record containing this source record. |
| `source_record_id` | TEXT | no | PK (2) | derived | Member source record identity. |
| `version_id` | TEXT | no | FK → `raw_customer_records.version_id` | derived | Member version used in this computation. |

## `raw_customer_records`

**Grain:** one delivered version of one source record.

| Column | SQLite type | Nullable | Key | Source or derived | Description |
|---|---|---|---|---|---|
| `version_id` | TEXT | no | PK | derived | Deterministic identity of this delivered version. |
| `source_record_id` | TEXT | no | — | derived | Stable identity of the logical source record. |
| `row_hash` | TEXT | no | — | derived | Fingerprint of original field values. |
| `source_system` | TEXT | no | — | source | Original source system value exactly as received. |
| `source_system_key` | TEXT | no | FK → `source_systems.source_system` | derived | Trimmed uppercase source system key used for referential integrity. |
| `source_native_id` | TEXT | no | — | source | Original identifier in the source system. |
| `full_name` | TEXT | no | — | source | Original customer name. |
| `email` | TEXT | yes | — | source | Original email value. |
| `phone` | TEXT | yes | — | source | Original phone value. |
| `address` | TEXT | yes | — | source | Original address value. |
| `postcode` | TEXT | yes | — | source | Original postcode value. |
| `dob` | TEXT | yes | — | source | Original date of birth value. |
| `updated_at` | TEXT | no | — | source | Original source update timestamp. |
| `source_file` | TEXT | yes | — | derived | Input file basename. |
| `source_row_number` | INTEGER | yes | — | derived | One-based CSV row number including the header. |
| `first_seen_run_id` | TEXT | no | FK → `runs.run_id` | derived | Run that first stored this version. |

## `rejects`

**Grain:** one rejected input row.

| Column | SQLite type | Nullable | Key | Source or derived | Description |
|---|---|---|---|---|---|
| `reject_id` | INTEGER | no | PK | derived | SQLite-assigned surrogate key for a rejected row. |
| `source_file` | TEXT | yes | — | derived | Input file basename. |
| `source_row_number` | INTEGER | yes | — | derived | One-based CSV row number including the header. |
| `reason_code` | TEXT | yes | — | derived | Validation reason for rejection. |
| `raw_line` | TEXT | yes | — | source | Original rejected CSV line. |
| `raw_line_hash` | TEXT | yes | — | derived | Fingerprint of the original rejected line. |
| `first_seen_run_id` | TEXT | yes | FK → `runs.run_id` | derived | Run that first recorded this rejection. |

## `review_decisions`

**Grain:** one human decision (never deleted).

| Column | SQLite type | Nullable | Key | Source or derived | Description |
|---|---|---|---|---|---|
| `pair_id` | TEXT | no | PK | derived | Stable identity of the reviewed source-record pair. |
| `decision` | TEXT | no | — | source | Human decision for the pair. |
| `reviewer` | TEXT | yes | — | source | Reviewer identifier, when supplied. |
| `decided_at` | TEXT | yes | — | source | UTC time the decision was recorded. |
| `note` | TEXT | yes | — | source | Optional reviewer note. |

## `review_queue`

**Grain:** one uncertain pair in the current computation (regenerated each run).

| Column | SQLite type | Nullable | Key | Source or derived | Description |
|---|---|---|---|---|---|
| `pair_id` | TEXT | no | PK, FK → `candidate_pairs.pair_id` | derived | Candidate pair awaiting or carrying a review decision. |
| `score` | REAL | no | — | derived | Pair score shown to reviewers. |
| `reason_code` | TEXT | no | — | derived | Reason the pair was sent to review. |
| `status` | TEXT | no | — | derived | Pending or recorded reviewer decision. |
| `run_id` | TEXT | no | FK → `runs.run_id` | derived | Run that generated this queue row. |

## `runs`

**Grain:** one pipeline execution.

| Column | SQLite type | Nullable | Key | Source or derived | Description |
|---|---|---|---|---|---|
| `run_id` | TEXT | no | PK | derived | Unique identity of one pipeline execution. |
| `started_at` | TEXT | no | — | derived | UTC time the run started. |
| `ended_at` | TEXT | yes | — | derived | UTC time the run finished, or NULL while running. |
| `status` | TEXT | no | — | derived | Execution status. |
| `input_files` | TEXT | no | — | derived | JSON array of input file names. |
| `input_rows` | INTEGER | no | — | derived | Number of input data rows. |
| `rejected_rows` | INTEGER | no | — | derived | Number of rejected input rows. |
| `valid_rows` | INTEGER | no | — | derived | Rows that passed input validation. |
| `new_version_rows` | INTEGER | no | — | derived | Newly stored valid versions. |
| `duplicate_event_rows` | INTEGER | no | — | derived | Valid deliveries already stored as versions. |
| `unique_source_records` | INTEGER | no | — | derived | Distinct source records in stored history. |
| `golden_records` | INTEGER | no | — | derived | Number of published golden customers. |
| `merged_away` | INTEGER | no | — | derived | Source records merged into other records. |
| `records_in_merged_clusters` | INTEGER | no | — | derived | Source records belonging to multi-member golden records. |
| `review_pending` | INTEGER | no | — | derived | Number of pending review pairs. |
| `records_in_pending_review` | INTEGER | no | — | derived | Distinct source records appearing in pending review pairs. |
| `metrics_json` | TEXT | no | — | derived | JSON object of run metrics. |
| `config_snapshot` | TEXT | no | — | derived | JSON snapshot of effective run configuration. |
| `error_message` | TEXT | yes | — | derived | Failure detail, if any. |

## `source_systems`

**Grain:** one source system.

| Column | SQLite type | Nullable | Key | Source or derived | Description |
|---|---|---|---|---|---|
| `source_system` | TEXT | no | PK | source | Canonical source system key. |
| `priority` | INTEGER | no | — | source | Configured survivorship priority. |
