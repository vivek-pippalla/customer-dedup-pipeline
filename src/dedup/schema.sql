CREATE TABLE IF NOT EXISTS source_systems (
    source_system TEXT PRIMARY KEY NOT NULL,
    priority INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    status TEXT NOT NULL CHECK (status IN ('running', 'success', 'success_empty', 'failed')),
    input_files TEXT NOT NULL DEFAULT '[]',
    input_rows INTEGER NOT NULL DEFAULT 0,
    rejected_rows INTEGER NOT NULL DEFAULT 0,
    valid_rows INTEGER NOT NULL DEFAULT 0,
    new_version_rows INTEGER NOT NULL DEFAULT 0,
    duplicate_event_rows INTEGER NOT NULL DEFAULT 0,
    unique_source_records INTEGER NOT NULL DEFAULT 0,
    golden_records INTEGER NOT NULL DEFAULT 0,
    merged_away INTEGER NOT NULL DEFAULT 0,
    records_in_merged_clusters INTEGER NOT NULL DEFAULT 0,
    review_pending INTEGER NOT NULL DEFAULT 0,
    records_in_pending_review INTEGER NOT NULL DEFAULT 0,
    metrics_json TEXT NOT NULL DEFAULT '{}',
    config_snapshot TEXT NOT NULL DEFAULT '{}',
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS raw_customer_records (
    version_id TEXT PRIMARY KEY NOT NULL,
    source_record_id TEXT NOT NULL,
    row_hash TEXT NOT NULL,
    source_system TEXT NOT NULL,
    source_system_key TEXT NOT NULL REFERENCES source_systems(source_system),
    source_native_id TEXT NOT NULL,
    full_name TEXT NOT NULL,
    email TEXT,
    phone TEXT,
    address TEXT,
    postcode TEXT,
    dob TEXT,
    updated_at TEXT NOT NULL,
    source_file TEXT,
    source_row_number INTEGER,
    first_seen_run_id TEXT NOT NULL REFERENCES runs(run_id),
    UNIQUE (source_record_id, row_hash)
);

CREATE TABLE IF NOT EXISTS rejects (
    reject_id INTEGER PRIMARY KEY,
    source_file TEXT,
    source_row_number INTEGER,
    reason_code TEXT,
    raw_line TEXT,
    raw_line_hash TEXT,
    first_seen_run_id TEXT REFERENCES runs(run_id),
    UNIQUE (source_file, source_row_number, raw_line_hash)
);

CREATE TABLE IF NOT EXISTS clean_customers (
    version_id TEXT PRIMARY KEY NOT NULL REFERENCES raw_customer_records(version_id),
    source_record_id TEXT NOT NULL,
    email_norm TEXT,
    phone_norm TEXT,
    name_norm TEXT,
    first_name_canon TEXT,
    first_is_initial INTEGER CHECK (first_is_initial IN (0, 1)),
    last_name_norm TEXT,
    address_norm TEXT,
    postcode_norm TEXT,
    updated_at_utc TEXT,
    dob_norm TEXT,
    soundex_last TEXT
);

CREATE TABLE IF NOT EXISTS candidate_pairs (
    pair_id TEXT PRIMARY KEY NOT NULL,
    source_record_id_a TEXT NOT NULL,
    source_record_id_b TEXT NOT NULL,
    email_score REAL,
    phone_score REAL,
    name_score REAL,
    address_score REAL,
    dob_score REAL,
    score REAL NOT NULL,
    coverage REAL NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('auto_merge', 'review')),
    reason_code TEXT NOT NULL,
    match_tier TEXT,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    CHECK (source_record_id_a < source_record_id_b)
);

CREATE TABLE IF NOT EXISTS golden_customers (
    golden_id TEXT PRIMARY KEY NOT NULL,
    full_name TEXT,
    email TEXT,
    phone TEXT,
    address TEXT,
    postcode TEXT,
    dob TEXT,
    member_count INTEGER NOT NULL,
    match_tier TEXT NOT NULL,
    latest_updated_at_utc TEXT,
    run_id TEXT NOT NULL REFERENCES runs(run_id)
);

CREATE TABLE IF NOT EXISTS golden_members (
    golden_id TEXT NOT NULL REFERENCES golden_customers(golden_id),
    source_record_id TEXT NOT NULL,
    version_id TEXT NOT NULL REFERENCES raw_customer_records(version_id),
    PRIMARY KEY (golden_id, source_record_id)
);

CREATE TABLE IF NOT EXISTS golden_lineage (
    golden_id TEXT NOT NULL REFERENCES golden_customers(golden_id),
    field_name TEXT NOT NULL,
    value TEXT,
    version_id TEXT REFERENCES raw_customer_records(version_id),
    source_record_id TEXT,
    source_system TEXT REFERENCES source_systems(source_system),
    rule_applied TEXT NOT NULL,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    PRIMARY KEY (golden_id, field_name)
);

CREATE TABLE IF NOT EXISTS review_queue (
    pair_id TEXT PRIMARY KEY NOT NULL REFERENCES candidate_pairs(pair_id),
    score REAL NOT NULL,
    reason_code TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'merge', 'not_merge')),
    run_id TEXT NOT NULL REFERENCES runs(run_id)
);

CREATE TABLE IF NOT EXISTS review_decisions (
    pair_id TEXT PRIMARY KEY NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('merge', 'not_merge')),
    reviewer TEXT,
    decided_at TEXT,
    note TEXT
);

CREATE INDEX IF NOT EXISTS idx_raw_customer_records_source_record_id
    ON raw_customer_records(source_record_id);
CREATE INDEX IF NOT EXISTS idx_clean_customers_source_record_id
    ON clean_customers(source_record_id);
CREATE INDEX IF NOT EXISTS idx_golden_members_source_record_id
    ON golden_members(source_record_id);
CREATE INDEX IF NOT EXISTS idx_candidate_pairs_source_record_id_a
    ON candidate_pairs(source_record_id_a);
CREATE INDEX IF NOT EXISTS idx_candidate_pairs_source_record_id_b
    ON candidate_pairs(source_record_id_b);
