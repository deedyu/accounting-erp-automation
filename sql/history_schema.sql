PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS automation_runs (
 run_id TEXT PRIMARY KEY, processed_at TEXT NOT NULL, source_file TEXT NOT NULL,
 sheet_name TEXT NOT NULL, summary_json TEXT NOT NULL, output_paths_json TEXT NOT NULL,
 snapshot_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS automation_files (
 run_id TEXT PRIMARY KEY REFERENCES automation_runs(run_id),
 source_hash TEXT NOT NULL, source_name TEXT NOT NULL, options_json TEXT NOT NULL,
 raw_json TEXT NOT NULL, unmapped_json TEXT NOT NULL, excluded_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS automation_mappings (
 run_id TEXT NOT NULL REFERENCES automation_runs(run_id), source_column TEXT NOT NULL,
 standard_column TEXT, confidence REAL NOT NULL, status TEXT NOT NULL, matched_alias TEXT,
 PRIMARY KEY (run_id, source_column)
);
CREATE TABLE IF NOT EXISTS automation_vouchers (
 run_id TEXT NOT NULL REFERENCES automation_runs(run_id), row_id TEXT NOT NULL,
 voucher_id TEXT, row_number INTEGER NOT NULL, transaction_date TEXT,
 processing_status TEXT NOT NULL, payload_json TEXT NOT NULL,
 PRIMARY KEY (run_id, row_id)
);
CREATE TABLE IF NOT EXISTS automation_errors (
 error_id INTEGER PRIMARY KEY, run_id TEXT NOT NULL, row_id TEXT NOT NULL,
 voucher_id TEXT, row_number INTEGER NOT NULL, error_column TEXT NOT NULL,
 error_type TEXT NOT NULL, severity TEXT NOT NULL CHECK(severity IN ('ERROR','WARNING','INFO')), detail TEXT NOT NULL,
 FOREIGN KEY (run_id, row_id) REFERENCES automation_vouchers(run_id, row_id)
);
CREATE TABLE IF NOT EXISTS automation_erp_lines (
 run_id TEXT NOT NULL, row_id TEXT NOT NULL, voucher_id TEXT NOT NULL,
 line_no INTEGER NOT NULL, transaction_date TEXT NOT NULL, account_code TEXT NOT NULL,
 debit_amount INTEGER NOT NULL, credit_amount INTEGER NOT NULL, amount INTEGER NOT NULL,
 payload_json TEXT NOT NULL, PRIMARY KEY (run_id, voucher_id, line_no),
 FOREIGN KEY (run_id, row_id) REFERENCES automation_vouchers(run_id, row_id)
);
CREATE TABLE IF NOT EXISTS automation_daily_totals (
 run_id TEXT NOT NULL REFERENCES automation_runs(run_id), scope TEXT NOT NULL,
 transaction_date TEXT NOT NULL, transaction_count INTEGER NOT NULL,
 debit_total INTEGER NOT NULL, credit_total INTEGER NOT NULL, difference INTEGER NOT NULL,
 unparsed_amount_count INTEGER NOT NULL, balance_status TEXT NOT NULL,
 PRIMARY KEY (run_id, scope, transaction_date)
);
CREATE INDEX IF NOT EXISTS automation_runs_date ON automation_runs(processed_at);
CREATE INDEX IF NOT EXISTS automation_voucher_status ON automation_vouchers(run_id, processing_status);
CREATE INDEX IF NOT EXISTS automation_error_severity ON automation_errors(run_id, severity);
