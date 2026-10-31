-- Queries for the SQLite shell. Run with: sqlite3 path\to\pipeline.db < sql/sample_queries.sql
-- Each section is a standalone SELECT. Adjust literal filters where noted.

-- QUERY: reconciliation_identities
-- Expected and actual values for the batch, database, aggregate, rejects-by-reason,
-- and golden-member reconciliation checks. The latest run supplies batch counts.
WITH latest AS (
    SELECT * FROM runs ORDER BY started_at DESC, run_id DESC LIMIT 1
), checks AS (
    SELECT 'batch: input_rows = rejects + valid' AS identity,
           input_rows AS expected,
           rejected_rows + new_version_rows + duplicate_event_rows AS actual
    FROM latest
    UNION ALL
    SELECT 'database: unique = golden + merged_away', unique_source_records,
           golden_records + merged_away FROM latest
    UNION ALL
    SELECT 'database: unique = SUM(member_count)', unique_source_records,
           (SELECT COALESCE(SUM(member_count), 0) FROM golden_customers)
    FROM latest
    UNION ALL
    SELECT 'aggregate: merged members - merged_away = multi-member goldens',
           records_in_merged_clusters - merged_away,
           (SELECT COUNT(*) FROM golden_customers WHERE member_count >= 2)
    FROM latest
    UNION ALL
    SELECT 'rejects: rejected_rows = sum(rejects_by_reason)', rejected_rows,
           (SELECT COALESCE(SUM(CAST(value AS INTEGER)), 0)
            FROM json_each(latest.metrics_json, '$.rejects_by_reason'))
    FROM latest
    UNION ALL
    SELECT 'members: unique = golden_members rows', unique_source_records,
           (SELECT COUNT(*) FROM golden_members)
    FROM latest
)
SELECT identity, expected, actual, expected = actual AS passed
FROM checks ORDER BY identity;

-- QUERY: foreign_key_orphans
-- One row per declared FK, each orphan_count must be zero. Nullable FK values are excluded.
SELECT 'raw_customer_records.source_system_key -> source_systems' AS foreign_key,
       COUNT(*) AS orphan_count FROM raw_customer_records r
WHERE NOT EXISTS (SELECT 1 FROM source_systems s WHERE s.source_system = r.source_system_key)
UNION ALL
SELECT 'raw_customer_records.first_seen_run_id -> runs', COUNT(*) FROM raw_customer_records r
WHERE NOT EXISTS (SELECT 1 FROM runs x WHERE x.run_id = r.first_seen_run_id)
UNION ALL
SELECT 'rejects.first_seen_run_id -> runs', COUNT(*) FROM rejects r
WHERE r.first_seen_run_id IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM runs x WHERE x.run_id = r.first_seen_run_id)
UNION ALL
SELECT 'clean_customers.version_id -> raw_customer_records', COUNT(*) FROM clean_customers c
WHERE NOT EXISTS (SELECT 1 FROM raw_customer_records r WHERE r.version_id = c.version_id)
UNION ALL
SELECT 'candidate_pairs.run_id -> runs', COUNT(*) FROM candidate_pairs p
WHERE NOT EXISTS (SELECT 1 FROM runs x WHERE x.run_id = p.run_id)
UNION ALL
SELECT 'golden_customers.run_id -> runs', COUNT(*) FROM golden_customers g
WHERE NOT EXISTS (SELECT 1 FROM runs x WHERE x.run_id = g.run_id)
UNION ALL
SELECT 'golden_members.golden_id -> golden_customers', COUNT(*) FROM golden_members m
WHERE NOT EXISTS (SELECT 1 FROM golden_customers g WHERE g.golden_id = m.golden_id)
UNION ALL
SELECT 'golden_members.version_id -> raw_customer_records', COUNT(*) FROM golden_members m
WHERE NOT EXISTS (SELECT 1 FROM raw_customer_records r WHERE r.version_id = m.version_id)
UNION ALL
SELECT 'golden_lineage.golden_id -> golden_customers', COUNT(*) FROM golden_lineage l
WHERE NOT EXISTS (SELECT 1 FROM golden_customers g WHERE g.golden_id = l.golden_id)
UNION ALL
SELECT 'golden_lineage.version_id -> raw_customer_records', COUNT(*) FROM golden_lineage l
WHERE l.version_id IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM raw_customer_records r WHERE r.version_id = l.version_id)
UNION ALL
SELECT 'golden_lineage.source_system -> source_systems', COUNT(*) FROM golden_lineage l
WHERE l.source_system IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM source_systems s WHERE s.source_system = l.source_system)
UNION ALL
SELECT 'golden_lineage.run_id -> runs', COUNT(*) FROM golden_lineage l
WHERE NOT EXISTS (SELECT 1 FROM runs x WHERE x.run_id = l.run_id)
UNION ALL
SELECT 'review_queue.pair_id -> candidate_pairs', COUNT(*) FROM review_queue q
WHERE NOT EXISTS (SELECT 1 FROM candidate_pairs p WHERE p.pair_id = q.pair_id)
UNION ALL
SELECT 'review_queue.run_id -> runs', COUNT(*) FROM review_queue q
WHERE NOT EXISTS (SELECT 1 FROM runs x WHERE x.run_id = q.run_id)
ORDER BY foreign_key;

-- QUERY: rejects_by_reason
SELECT reason_code, COUNT(*) AS reject_count
FROM rejects
GROUP BY reason_code
ORDER BY reason_code;

-- QUERY: largest_clusters_with_members
WITH largest AS (
    SELECT golden_id, full_name, member_count
    FROM golden_customers
    WHERE member_count >= 2
    ORDER BY member_count DESC, golden_id
    LIMIT 10
)
SELECT l.golden_id, l.full_name AS golden_name, l.member_count,
       m.source_record_id, r.source_system, r.source_native_id, r.full_name AS source_name
FROM largest l
JOIN golden_members m USING (golden_id)
JOIN raw_customer_records r USING (version_id)
ORDER BY l.member_count DESC, l.golden_id, m.source_record_id;

-- QUERY: three_source_rows_one_golden_lineage
-- Selects one deterministic three-member golden record and shows every field's lineage.
-- To inspect a known cluster instead, replace the selected CTE with:
-- SELECT 'your_golden_id' AS golden_id
WITH selected AS (
    SELECT golden_id FROM golden_customers
    WHERE member_count = 3
    ORDER BY golden_id
    LIMIT 1
)
SELECT g.golden_id, g.full_name AS golden_name, g.member_count,
       l.field_name, l.value, l.source_record_id, l.version_id,
       l.source_system, l.rule_applied
FROM selected s
JOIN golden_customers g USING (golden_id)
JOIN golden_lineage l USING (golden_id)
ORDER BY l.field_name;

-- QUERY: review_queue_with_both_records
WITH current_records AS (
    SELECT c.source_record_id, r.full_name, r.email, r.phone,
           ROW_NUMBER() OVER (
               PARTITION BY c.source_record_id
               ORDER BY c.updated_at_utc DESC, r.row_hash ASC
           ) AS version_rank
    FROM clean_customers c
    JOIN raw_customer_records r USING (version_id)
)
SELECT q.pair_id, q.reason_code, q.score, q.status,
       p.source_record_id_a, a.full_name AS name_a, a.email AS email_a, a.phone AS phone_a,
       p.source_record_id_b, b.full_name AS name_b, b.email AS email_b, b.phone AS phone_b
FROM review_queue q
JOIN candidate_pairs p USING (pair_id)
JOIN current_records a ON a.source_record_id = p.source_record_id_a AND a.version_rank = 1
JOIN current_records b ON b.source_record_id = p.source_record_id_b AND b.version_rank = 1
ORDER BY q.reason_code, q.pair_id;

-- QUERY: merged_away_by_source_system
-- The smallest source_record_id is the deterministic cluster root; all other members
-- are counted as merged away for this source-system attribution.
WITH ranked_members AS (
    SELECT m.golden_id, m.source_record_id, r.source_system,
           ROW_NUMBER() OVER (PARTITION BY m.golden_id ORDER BY m.source_record_id) AS member_rank
    FROM golden_members m
    JOIN golden_customers g USING (golden_id)
    JOIN raw_customer_records r USING (version_id)
    WHERE g.member_count >= 2
), counts AS (
    SELECT source_system, COUNT(*) AS merged_away_count
    FROM ranked_members
    WHERE member_rank > 1
    GROUP BY source_system
)
SELECT s.source_system, COALESCE(c.merged_away_count, 0) AS merged_away_count
FROM source_systems s
LEFT JOIN counts c USING (source_system)
ORDER BY s.source_system;

-- QUERY: version_and_duplicate_event_counts_by_run
SELECT run_id, started_at, status, input_rows, valid_rows,
       new_version_rows, duplicate_event_rows, rejected_rows
FROM runs
ORDER BY started_at, run_id;
