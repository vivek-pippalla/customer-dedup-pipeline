# Project checklist

## Required edge cases

| Done | Edge case | Evidence |
|---|---|---|
| [ ] | Malformed CSV row is rejected and processing continues | |
| [ ] | Missing required field is rejected | |
| [ ] | Duplicate key and duplicate event handling is deterministic | |
| [ ] | Unexpected schema change fails clearly; extra columns are ignored | |
| [ ] | Empty batch leaves outputs unchanged | |
| [ ] | Partial publish failure preserves prior output and can be retried | |
| [ ] | Late or out-of-order data does not replace newer values | |
| [ ] | Invalid source system is rejected | |
| [ ] | Rerunning the same input creates no duplicates | |

## Acceptance criteria

| Done | Criterion | Evidence |
|---|---|---|
| [ ] | Keys and referential integrity are checked | |
| [ ] | Transforms are deterministic | |
| [ ] | Counts and aggregates reconcile | |
| [ ] | Invalid records are traceable | |
| [ ] | Reruns create no duplicates | |
| [ ] | Tests pass | |
| [ ] | Clean-environment setup works | |
