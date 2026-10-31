# Seed 1: original defaults vs. recommended name-forward settings

## Reproducibility

Both measurements use the existing `data/generated/dev_seed1_20000.csv` and its matching `data/generated/dev_seed1_20000_truth.csv`. The data was not regenerated. Each profile ran the full pipeline in its own temporary SQLite database and was evaluated against the same truth file. Both runs used the explicit as-of timestamp `2026-10-31T00:00:00Z`. `config/default.toml` was not edited.

The original profile uses the Build Plan v3 defaults: auto `0.90`, review `0.65`, `last_name_min_jw` `0.90`, and weights email/phone/name/address/DOB = `0.30/0.25/0.25/0.10/0.10`.

The recommended name-forward profile uses auto `0.85`, review `0.75`, `last_name_min_jw` `0.85`, and weights email/phone/name/address/DOB = `0.25/0.25/0.30/0.10/0.10`.

Each profile was run from the repository root using `.venv\\Scripts\\python.exe -` with an inline Python driver that loaded `config/default.toml`, applied the profile values in memory, created a separate temporary database with `init_schema`, called `run_pipeline(..., as_of="2026-10-31T00:00:00Z")`, then called `evaluate_database` with the matching truth file. The driver deleted each temporary database after collecting the metrics. The invocation was:

```text
.venv\\Scripts\\python.exe -
```

The driver used `data/generated/dev_seed1_20000.csv` as its only input file. No persistent config or dataset was changed.

## Results

The evaluator's cluster metrics count all predicted pairs within final clusters. Auto-merge precision is reported separately for pre-clustering auto-merge pairs.

| Metric | Build Plan v3 defaults | Recommended name-forward | Difference (recommended minus defaults) |
|---|---:|---:|---:|
| Cluster precision | 1.0000 (100.00%) | 1.0000 (100.00%) | 0.0000 (0.00 pp) |
| Cluster recall | 0.7188 (71.88%) | 0.7348 (73.48%) | +0.0160 (+1.60 pp) |
| Cluster F1 | 0.8364 (83.64%) | 0.8471 (84.71%) | +0.0107 (+1.07 pp) |
| Auto-merge precision | 1.0000 (100.00%) | 1.0000 (100.00%) | 0.0000 (0.00 pp) |
| False auto-merges | 0 | 0 | 0 |
| Review queue size | 4,166 | 4,056 | -110 (-2.64%) |

Both runs evaluated against 5,434 true duplicate pairs and accepted 17,200 valid rows from 20,000 input rows (2,800 rejected). Neither evaluation found any false cluster pairs. The original-defaults run produced 3,906 within-cluster predicted pairs.

## Interpretation

On this seed-1 synthetic dataset, the name-forward profile improved cluster recall by 1.60 percentage points and F1 by 1.07 points while preserving the measured 100% precision and zero false auto-merges. It also reduced the review queue by 110 pairs. This is an observed difference on this dataset, not evidence that the same performance will hold on real customer data.
