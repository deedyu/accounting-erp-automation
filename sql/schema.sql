-- SQLite에서 외래키 제약조건을 사용하도록 설정
PRAGMA foreign_keys = ON;


-- 계정과목 기준정보
CREATE TABLE IF NOT EXISTS accounts (
    account_code INTEGER PRIMARY KEY,
    account_name TEXT NOT NULL,
    account_category TEXT NOT NULL,
    normal_balance TEXT NOT NULL,
    vat_type TEXT NOT NULL,
    is_active TEXT NOT NULL
);


-- 거래처 기준정보
CREATE TABLE IF NOT EXISTS partners (
    partner_code TEXT PRIMARY KEY,
    partner_name TEXT NOT NULL,
    partner_type TEXT NOT NULL,
    default_account_code INTEGER NOT NULL,
    settlement_account_code INTEGER NOT NULL,
    payment_method TEXT NOT NULL,
    vat_applicable TEXT NOT NULL,
    is_active TEXT NOT NULL,

    FOREIGN KEY (
        default_account_code
    ) REFERENCES accounts (
        account_code
    ),

    FOREIGN KEY (
        settlement_account_code
    ) REFERENCES accounts (
        account_code
    )
);


-- 부서 기준정보
CREATE TABLE IF NOT EXISTS departments (
    department_code TEXT PRIMARY KEY,
    department_name TEXT NOT NULL,
    cost_center TEXT NOT NULL,
    main_role TEXT NOT NULL,
    is_active TEXT NOT NULL
);


-- ERP 입력 전 원본 데이터를 보관하는 임시 테이블
CREATE TABLE IF NOT EXISTS staging_transactions (
    voucher_id TEXT PRIMARY KEY,
    transaction_date TEXT,
    transaction_type TEXT,
    department_code TEXT,
    partner_code TEXT,
    evidence_type TEXT,
    evidence_no TEXT,
    description TEXT,

    debit_account_1 INTEGER,
    debit_amount_1 INTEGER,
    debit_account_2 INTEGER,
    debit_amount_2 INTEGER,

    credit_account_1 INTEGER,
    credit_amount_1 INTEGER,
    credit_account_2 INTEGER,
    credit_amount_2 INTEGER,

    supply_amount INTEGER,
    vat_amount INTEGER,
    total_amount INTEGER,
    remarks TEXT,

    error_count INTEGER NOT NULL DEFAULT 0,
    error_types TEXT NOT NULL DEFAULT '없음',
    processing_status TEXT NOT NULL
);


-- 검증 과정에서 발견된 오류 이력
CREATE TABLE IF NOT EXISTS validation_errors (
    validation_error_id INTEGER PRIMARY KEY AUTOINCREMENT,
    voucher_id TEXT NOT NULL,
    error_column TEXT NOT NULL,
    error_type TEXT NOT NULL,
    detail TEXT NOT NULL,

    FOREIGN KEY (
        voucher_id
    ) REFERENCES staging_transactions (
        voucher_id
    )
);


-- 검증을 통과해 ERP 입력이 허용된 전표의 기본정보
CREATE TABLE IF NOT EXISTS erp_vouchers (
    voucher_id TEXT PRIMARY KEY,
    transaction_date TEXT NOT NULL,
    transaction_type TEXT NOT NULL,
    department_code TEXT NOT NULL,
    partner_code TEXT NOT NULL,
    evidence_type TEXT NOT NULL,
    evidence_no TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL,
    remarks TEXT,

    FOREIGN KEY (
        department_code
    ) REFERENCES departments (
        department_code
    ),

    FOREIGN KEY (
        partner_code
    ) REFERENCES partners (
        partner_code
    )
);


-- ERP 전표에 포함되는 차변·대변 분개 행
CREATE TABLE IF NOT EXISTS journal_lines (
    voucher_id TEXT NOT NULL,
    line_no INTEGER NOT NULL,
    debit_credit_type TEXT NOT NULL,
    account_code INTEGER NOT NULL,
    amount INTEGER NOT NULL,

    PRIMARY KEY (
        voucher_id,
        line_no
    ),

    FOREIGN KEY (
        voucher_id
    ) REFERENCES erp_vouchers (
        voucher_id
    ),

    FOREIGN KEY (
        account_code
    ) REFERENCES accounts (
        account_code
    )
);


-- 처리 상태별 조회 성능을 높이기 위한 인덱스
CREATE INDEX IF NOT EXISTS idx_staging_status
ON staging_transactions (
    processing_status
);


-- 오류 유형별 조회 성능을 높이기 위한 인덱스
CREATE INDEX IF NOT EXISTS idx_validation_error_type
ON validation_errors (
    error_type
);


-- 부서별 ERP 전표 조회를 위한 인덱스
CREATE INDEX IF NOT EXISTS idx_erp_department
ON erp_vouchers (
    department_code
);


-- 계정과목별 분개 조회를 위한 인덱스
CREATE INDEX IF NOT EXISTS idx_journal_account
ON journal_lines (
    account_code
);