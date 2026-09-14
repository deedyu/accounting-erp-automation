"""마스터 데이터와 회계 처리 결과를 SQLite 데이터베이스에 적재한다."""

import sqlite3
import pandas as pd

from journal_validator import PROJECT_ROOT


# 데이터베이스와 SQL 설계 파일 경로
DATABASE_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "accounting_erp.db"
)

SCHEMA_PATH = (
    PROJECT_ROOT
    / "sql"
    / "schema.sql"
)


def load_source_files():
    """데이터베이스에 적재할 CSV 파일을 불러온다."""

    accounts_path = (
        PROJECT_ROOT
        / "data"
        / "master"
        / "accounts.csv"
    )

    partners_path = (
        PROJECT_ROOT
        / "data"
        / "master"
        / "vendors.csv"
    )

    departments_path = (
        PROJECT_ROOT
        / "data"
        / "master"
        / "departments.csv"
    )

    staging_path = (
        PROJECT_ROOT
        / "data"
        / "processed"
        / "bulk_transaction_status.csv"
    )

    validation_path = (
        PROJECT_ROOT
        / "data"
        / "processed"
        / "bulk_validation_result.csv"
    )

    erp_upload_path = (
        PROJECT_ROOT
        / "data"
        / "processed"
        / "bulk_erp_upload.csv"
    )

    required_paths = [
        accounts_path,
        partners_path,
        departments_path,
        staging_path,
        validation_path,
        erp_upload_path,
        SCHEMA_PATH
    ]

    # 필수 파일이 하나라도 없으면 적재 중단
    for file_path in required_paths:
        if not file_path.exists():
            raise FileNotFoundError(
                f"필수 파일 없음: {file_path}"
            )

    # 기준정보 불러오기
    accounts = pd.read_csv(accounts_path)
    partners = pd.read_csv(partners_path)
    departments = pd.read_csv(
        departments_path
    )

    # 검증과 ERP 변환 결과 불러오기
    staging_transactions = pd.read_csv(
        staging_path
    )

    validation_errors = pd.read_csv(
        validation_path
    )

    erp_upload = pd.read_csv(
        erp_upload_path
    )

    return {
        "accounts": accounts,
        "partners": partners,
        "departments": departments,
        "staging_transactions": (
            staging_transactions
        ),
        "validation_errors": validation_errors,
        "erp_upload": erp_upload
    }


def prepare_database_tables(source_data):
    """CSV 데이터를 데이터베이스 테이블 구조에 맞게 변환한다."""

    accounts = source_data[
        "accounts"
    ].copy()

    partners = source_data[
        "partners"
    ].copy()

    departments = source_data[
        "departments"
    ].copy()

    staging_transactions = source_data[
        "staging_transactions"
    ].copy()

    validation_errors = source_data[
        "validation_errors"
    ].copy()

    erp_upload = source_data[
        "erp_upload"
    ].copy()

    # validation_errors 테이블의 열 이름에 맞게 변경
    validation_errors = (
        validation_errors.rename(
            columns={
                "column": "error_column"
            }
        )
    )

    validation_errors = validation_errors[
        [
            "voucher_id",
            "error_column",
            "error_type",
            "detail"
        ]
    ]

    # ERP 업로드 데이터에서 전표 공통 정보만 추출
    erp_vouchers = (
        erp_upload[
            [
                "voucher_id",
                "transaction_date",
                "transaction_type",
                "department_code",
                "partner_code",
                "evidence_type",
                "evidence_no",
                "description",
                "remarks"
            ]
        ]
        .drop_duplicates(
            subset="voucher_id"
        )
        .reset_index(drop=True)
    )

    # ERP 업로드 데이터에서 분개 행만 추출
    journal_lines = erp_upload[
        [
            "voucher_id",
            "line_no",
            "debit_credit_type",
            "account_code",
            "amount"
        ]
    ].copy()

    # 데이터베이스 정수형에 맞게 변환
    accounts["account_code"] = (
        accounts["account_code"].astype(int)
    )

    partners["default_account_code"] = (
        partners[
            "default_account_code"
        ].astype(int)
    )

    partners["settlement_account_code"] = (
        partners[
            "settlement_account_code"
        ].astype(int)
    )

    journal_lines["line_no"] = (
        journal_lines["line_no"].astype(int)
    )

    journal_lines["account_code"] = (
        journal_lines[
            "account_code"
        ].astype(int)
    )

    journal_lines["amount"] = (
        journal_lines["amount"].astype(int)
    )

    return {
        "accounts": accounts,
        "partners": partners,
        "departments": departments,
        "staging_transactions": (
            staging_transactions
        ),
        "validation_errors": (
            validation_errors
        ),
        "erp_vouchers": erp_vouchers,
        "journal_lines": journal_lines
    }


def create_database_schema(connection):
    """schema.sql을 실행해 테이블과 인덱스를 생성한다."""

    with open(
        SCHEMA_PATH,
        "r",
        encoding="utf-8"
    ) as schema_file:
        schema_sql = schema_file.read()

    # SQL 파일에 작성된 여러 명령문을 한 번에 실행
    connection.executescript(schema_sql)


def clear_existing_data(connection):
    """프로그램 재실행을 위해 기존 테이블의 데이터를 비운다."""

    # 외래키 관계의 자식 테이블부터 삭제
    delete_statements = [
        "DELETE FROM journal_lines",
        "DELETE FROM erp_vouchers",
        "DELETE FROM validation_errors",
        "DELETE FROM staging_transactions",
        "DELETE FROM partners",
        "DELETE FROM departments",
        "DELETE FROM accounts"
    ]

    for statement in delete_statements:
        connection.execute(statement)


def insert_database_data(
    connection,
    database_tables
):
    """준비한 데이터를 외래키 순서에 맞게 적재한다."""

    # 기준정보를 먼저 적재
    database_tables["accounts"].to_sql(
        "accounts",
        connection,
        if_exists="append",
        index=False
    )

    database_tables["partners"].to_sql(
        "partners",
        connection,
        if_exists="append",
        index=False
    )

    database_tables["departments"].to_sql(
        "departments",
        connection,
        if_exists="append",
        index=False
    )

    # 검증 전 원본과 오류 결과 적재
    database_tables[
        "staging_transactions"
    ].to_sql(
        "staging_transactions",
        connection,
        if_exists="append",
        index=False
    )

    database_tables[
        "validation_errors"
    ].to_sql(
        "validation_errors",
        connection,
        if_exists="append",
        index=False
    )

    # 검증을 통과한 ERP 전표와 분개 행 적재
    database_tables["erp_vouchers"].to_sql(
        "erp_vouchers",
        connection,
        if_exists="append",
        index=False
    )

    database_tables["journal_lines"].to_sql(
        "journal_lines",
        connection,
        if_exists="append",
        index=False
    )


def verify_database(connection):
    """테이블별 건수와 외래키 무결성을 확인한다."""

    table_names = [
        "accounts",
        "partners",
        "departments",
        "staging_transactions",
        "validation_errors",
        "erp_vouchers",
        "journal_lines"
    ]

    table_counts = []

    # 각 테이블의 저장 건수 조회
    for table_name in table_names:
        query = (
            f"SELECT COUNT(*) "
            f"FROM {table_name}"
        )

        row_count = connection.execute(
            query
        ).fetchone()[0]

        table_counts.append(
            {
                "table_name": table_name,
                "row_count": row_count
            }
        )

    table_count_result = pd.DataFrame(
        table_counts
    )

    # 외래키 관계에 어긋난 데이터 조회
    foreign_key_errors = (
        connection
        .execute("PRAGMA foreign_key_check")
        .fetchall()
    )

    return (
        table_count_result,
        foreign_key_errors
    )


def main():
    """SQLite 데이터베이스 생성과 적재를 실행한다."""

    print("데이터베이스 적재 시작")

    # CSV 입력 파일 불러오기
    source_data = load_source_files()

    # 데이터베이스 테이블 구조에 맞게 변환
    database_tables = prepare_database_tables(
        source_data
    )

    # processed 폴더가 없으면 생성
    DATABASE_PATH.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    # SQLite 데이터베이스 연결
    connection = sqlite3.connect(
        DATABASE_PATH
    )

    try:
        # 외래키 검사를 현재 연결에서 활성화
        connection.execute(
            "PRAGMA foreign_keys = ON"
        )

        # 테이블 구조 생성
        create_database_schema(connection)

        # 여러 작업을 하나의 트랜잭션으로 처리
        with connection:
            clear_existing_data(connection)

            insert_database_data(
                connection,
                database_tables
            )

        # 적재 결과 검증
        (
            table_count_result,
            foreign_key_errors
        ) = verify_database(connection)

        print()
        print("테이블별 저장 건수")
        print(
            table_count_result.to_string(
                index=False
            )
        )

        print()
        print(
            "외래키 오류 수:",
            len(foreign_key_errors)
        )

        print()
        print(
            "데이터베이스 저장 위치:",
            DATABASE_PATH
        )

        print()
        print("데이터베이스 적재 완료")

    finally:
        # 오류 발생 여부와 관계없이 연결 종료
        connection.close()


if __name__ == "__main__":
    main()