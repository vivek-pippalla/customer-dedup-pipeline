# Design notes

## Assumptions

TODO: Review and record the assumptions from BUILD_PLAN.md section 15.1.

## Decisions

TODO: Explain the decisions from BUILD_PLAN.md section 15.2 and any implementation decisions not specified there.

### Phase 1 implementation choices

- `reject_id` uses SQLite's `INTEGER PRIMARY KEY` surrogate, as selected by the project owner; the plan defines no deterministic reject ID formula.
- `row_hash` treats a Python `None` optional field as an empty string before joining the original fields with `\x1f`; CSV empty optional fields are represented the same way.
- Injected naive clocks for `new_run_id` are treated as UTC. Run IDs use `YYYYMMDDTHHMMSSZ` followed by the four lowercase hexadecimal suffix characters.
- Schema initialization upserts configured source priorities so a later config change updates seeded priority values.
- `start_run` marks abandoned running rows before inserting and committing the new run row.
- Run rows include `valid_rows`, `records_in_merged_clusters`, and `records_in_pending_review` from the section 3.11 reconciliation counts, in addition to the section 5 listing.

### Phase 2A generator choices

- Unspecified generator defaults are `dup_rate=0.35`, `family_rate=0.10`, `invalid_rate=0.14`, `late_rate=0.10`, and `seed=1`; the CLI sample command supplies its own seed.
- `dup_rate` is the chance a new emitted row reuses an entity with fewer than four records; `family_rate` is the chance a newly created entity shares one identifier with an existing entity; `late_rate` is the chance an additional same-source version is older. A late pair is guaranteed when `late_rate` is positive and at least two rows are requested.
- If `family_rate` is positive and at least two entities are generated but random selection produced no family link, the generator adds one family link to ensure that case is represented.
- Invalid row count is rounded to the nearest integer, with at least one invalid row when the rate is positive and rows are requested. Duplicate-key victims are selected by the larger production `row_hash` within a two-row same-key, same-timestamp pair.
- Ground-truth `row_number` is the one-based data-row position within its source CSV (the header is excluded). For multiple batches, one combined truth file records each CSV basename.
- The manifest is named `<out stem>_manifest.json` beside the primary output path.

### Phase 2B ingestion choice

- Raw `source_system` remains byte-for-byte as received. `raw_customer_records.source_system_key` stores its trimmed uppercase form and references `source_systems`, allowing case- and whitespace-insensitive validation without rewriting source data.

## Trade-offs and limitations

TODO: Review BUILD_PLAN.md sections 13 and 15.3.

## Testing and evidence

TODO: Record the testing approach and evidence from actual runs.
