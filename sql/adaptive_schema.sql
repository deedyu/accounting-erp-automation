PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS processing_runs (
    run_id TEXT PRIMARY KEY,
    source_file TEXT NOT NULL,
    sheet_name TEXT NOT NULL,
    processed_at TEXT NOT NULL,
    period_start TEXT,
    period_end TEXT,
    total_transactions INTEGER NOT NULL,
    detected_errors INTEGER NOT NULL,
    error_transactions INTEGER NOT NULL,
    ready_transactions INTEGER NOT NULL,
    review_transactions INTEGER NOT NULL,
    review_rate REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS column_mappings (
    run_id TEXT NOT NULL,
    source_column TEXT NOT NULL,
    standard_column TEXT,
    matched_alias TEXT,
    confidence REAL NOT NULL,
    status TEXT NOT NULL,
    PRIMARY KEY (
        run_id,
        source_column
    ),
    FOREIGN KEY (run_id)
        REFERENCES processing_runs(run_id)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS processed_transactions (
    run_id TEXT NOT NULL,
    voucher_id TEXT NOT NULL,
    transaction_date TEXT,
    transaction_type TEXT,
    department_code TEXT,
    partner_code TEXT,
    evidence_type TEXT,
    evidence_no TEXT,
    description TEXT,
    debit_account_1 INTEGER,
    debit_amount_1 REAL,
    debit_account_2 INTEGER,
    debit_amount_2 REAL,
    credit_account_1 INTEGER,
    credit_amount_1 REAL,
    credit_account_2 INTEGER,
    credit_amount_2 REAL,
    supply_amount REAL,
    vat_amount REAL,
    total_amount REAL,
    remarks TEXT,
    error_count INTEGER NOT NULL,
    error_types TEXT NOT NULL,
    processing_status TEXT NOT NULL,
    PRIMARY KEY (
        run_id,
        voucher_id
    ),
    FOREIGN KEY (run_id)
        REFERENCES processing_runs(run_id)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS validation_errors (
    error_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    voucher_id TEXT NOT NULL,
    error_column TEXT NOT NULL,
    error_type TEXT NOT NULL,
    detail TEXT NOT NULL,
    FOREIGN KEY (
        run_id,
        voucher_id
    )
        REFERENCES processed_transactions(
            run_id,
            voucher_id
        )
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS erp_journal_lines (
    run_id TEXT NOT NULL,
    voucher_id TEXT NOT NULL,
    line_no INTEGER NOT NULL,
    transaction_date TEXT,
    transaction_type TEXT,
    department_code TEXT,
    partner_code TEXT,
    debit_credit_type TEXT NOT NULL,
    account_code INTEGER NOT NULL,
    account_name TEXT NOT NULL,
    amount REAL NOT NULL,
    evidence_type TEXT,
    evidence_no TEXT,
    description TEXT,
    remarks TEXT,
    PRIMARY KEY (
        run_id,
        voucher_id,
        line_no
    ),
    FOREIGN KEY (
        run_id,
        voucher_id
    )
        REFERENCES processed_transactions(
            run_id,
            voucher_id
        )
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_runs_processed_at
ON processing_runs(processed_at);

CREATE INDEX IF NOT EXISTS idx_transactions_status
ON processed_transactions(
    run_id,
    processing_status
);

CREATE INDEX IF NOT EXISTS idx_errors_type
ON validation_errors(
    run_id,
    error_type
);

CREATE INDEX IF NOT EXISTS idx_erp_account
ON erp_journal_lines(
    run_id,
    account_code
);