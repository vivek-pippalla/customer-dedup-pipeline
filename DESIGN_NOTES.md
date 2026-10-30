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

## Trade-offs and limitations

TODO: Review BUILD_PLAN.md sections 13 and 15.3.

## Testing and evidence

TODO: Record the testing approach and evidence from actual runs.
