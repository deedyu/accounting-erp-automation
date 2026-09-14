"""SQLite 데이터베이스의 운영 현황을 Tableau용 CSV로 저장한다."""

import sqlite3
import pandas as pd

from journal_validator import PROJECT_ROOT


# 데이터베이스 경로
DATABASE_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "accounting_erp.db"
)

# Tableau용 데이터 저장 폴더
DASHBOARD_DATA_DIR = (
    PROJECT_ROOT
    / "dashboard"
    / "data"
)


def build_dashboard_queries():
    """대시보드에 사용할 SQL 쿼리를 정의한다."""

    return {
        "dashboard_kpi": """
            SELECT
                COUNT(*) AS total_transactions,

                SUM(
                    CASE
                        WHEN processing_status = '입력 가능'
                        THEN 1
                        ELSE 0
                    END
                ) AS ready_transactions,

                SUM(
                    CASE
                        WHEN processing_status = '검토 필요'
                        THEN 1
                        ELSE 0
                    END
                ) AS review_transactions,

                ROUND(
                    SUM(
                        CASE
                            WHEN processing_status = '검토 필요'
                            THEN 1
                            ELSE 0
                        END
                    ) * 100.0 / COUNT(*),
                    1
                ) AS review_rate,

                SUM(total_amount) AS total_amount,

                ROUND(
                    AVG(total_amount),
                    0
                ) AS average_amount

            FROM staging_transactions
        """,

        "status_summary": """
            SELECT
                processing_status,
                COUNT(*) AS transaction_count,
                SUM(total_amount) AS total_amount,

                ROUND(
                    COUNT(*) * 100.0
                    / (
                        SELECT COUNT(*)
                        FROM staging_transactions
                    ),
                    1
                ) AS status_rate

            FROM staging_transactions

            GROUP BY processing_status

            ORDER BY transaction_count DESC
        """,

        "error_type_summary": """
            SELECT
                error_type,
                COUNT(*) AS error_count,

                ROUND(
                    COUNT(*) * 100.0
                    / (
                        SELECT COUNT(*)
                        FROM validation_errors
                    ),
                    1
                ) AS error_rate

            FROM validation_errors

            GROUP BY error_type

            ORDER BY error_count DESC, error_type
        """,

        "department_summary": """
            SELECT
                st.department_code,

                COALESCE(
                    d.department_name,
                    '미등록 부서'
                ) AS department_name,

                COUNT(*) AS transaction_count,

                SUM(
                    CASE
                        WHEN st.processing_status = '입력 가능'
                        THEN 1
                        ELSE 0
                    END
                ) AS ready_count,

                SUM(
                    CASE
                        WHEN st.processing_status = '검토 필요'
                        THEN 1
                        ELSE 0
                    END
                ) AS review_count,

                ROUND(
                    SUM(
                        CASE
                            WHEN st.processing_status = '검토 필요'
                            THEN 1
                            ELSE 0
                        END
                    ) * 100.0 / COUNT(*),
                    1
                ) AS review_rate

            FROM staging_transactions AS st

            LEFT JOIN departments AS d
                ON st.department_code = d.department_code

            GROUP BY
                st.department_code,
                d.department_name

            ORDER BY review_rate DESC, transaction_count DESC
        """,

        "transaction_type_summary": """
            SELECT
                transaction_type,
                COUNT(*) AS transaction_count,

                SUM(
                    CASE
                        WHEN processing_status = '입력 가능'
                        THEN 1
                        ELSE 0
                    END
                ) AS ready_count,

                SUM(
                    CASE
                        WHEN processing_status = '검토 필요'
                        THEN 1
                        ELSE 0
                    END
                ) AS review_count,

                ROUND(
                    SUM(
                        CASE
                            WHEN processing_status = '검토 필요'
                            THEN 1
                            ELSE 0
                        END
                    ) * 100.0 / COUNT(*),
                    1
                ) AS review_rate,

                SUM(total_amount) AS total_amount

            FROM staging_transactions

            GROUP BY transaction_type

            ORDER BY transaction_count DESC
        """,

        "daily_summary": """
            SELECT
                transaction_date,
                COUNT(*) AS transaction_count,

                SUM(
                    CASE
                        WHEN processing_status = '입력 가능'
                        THEN 1
                        ELSE 0
                    END
                ) AS ready_count,

                SUM(
                    CASE
                        WHEN processing_status = '검토 필요'
                        THEN 1
                        ELSE 0
                    END
                ) AS review_count,

                SUM(total_amount) AS total_amount

            FROM staging_transactions

            GROUP BY transaction_date

            ORDER BY transaction_date
        """,

        "account_summary": """
            SELECT
                jl.account_code,
                a.account_name,
                a.account_category,

                SUM(
                    CASE
                        WHEN jl.debit_credit_type = '차변'
                        THEN jl.amount
                        ELSE 0
                    END
                ) AS debit_amount,

                SUM(
                    CASE
                        WHEN jl.debit_credit_type = '대변'
                        THEN jl.amount
                        ELSE 0
                    END
                ) AS credit_amount,

                SUM(
                    CASE
                        WHEN jl.debit_credit_type = '차변'
                        THEN jl.amount
                        ELSE -jl.amount
                    END
                ) AS net_amount

            FROM journal_lines AS jl

            INNER JOIN accounts AS a
                ON jl.account_code = a.account_code

            GROUP BY
                jl.account_code,
                a.account_name,
                a.account_category

            ORDER BY
                a.account_category,
                jl.account_code
        """,

        "partner_summary": """
            SELECT
                st.partner_code,

                COALESCE(
                    p.partner_name,
                    '미등록 거래처'
                ) AS partner_name,

                COUNT(*) AS transaction_count,

                SUM(
                    CASE
                        WHEN st.processing_status = '검토 필요'
                        THEN 1
                        ELSE 0
                    END
                ) AS review_count,

                ROUND(
                    SUM(
                        CASE
                            WHEN st.processing_status = '검토 필요'
                            THEN 1
                            ELSE 0
                        END
                    ) * 100.0 / COUNT(*),
                    1
                ) AS review_rate,

                SUM(st.total_amount) AS total_amount

            FROM staging_transactions AS st

            LEFT JOIN partners AS p
                ON st.partner_code = p.partner_code

            GROUP BY
                st.partner_code,
                p.partner_name

            ORDER BY review_rate DESC, transaction_count DESC
        """,

        "review_detail": """
            SELECT
                st.voucher_id,
                st.transaction_date,
                st.transaction_type,

                COALESCE(
                    d.department_name,
                    st.department_code
                ) AS department,

                COALESCE(
                    p.partner_name,
                    st.partner_code
                ) AS partner,

                st.evidence_type,
                st.evidence_no,
                st.description,
                st.total_amount,
                ve.error_column,
                ve.error_type,
                ve.detail

            FROM staging_transactions AS st

            INNER JOIN validation_errors AS ve
                ON st.voucher_id = ve.voucher_id

            LEFT JOIN departments AS d
                ON st.department_code = d.department_code

            LEFT JOIN partners AS p
                ON st.partner_code = p.partner_code

            WHERE st.processing_status = '검토 필요'

            ORDER BY
                st.transaction_date,
                st.voucher_id
        """
    }


def export_dashboard_data(connection, queries):
    """SQL 쿼리를 실행하고 결과를 CSV로 저장한다."""

    DASHBOARD_DATA_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    export_results = []

    # 쿼리 이름과 SQL문을 하나씩 실행
    for query_name, query in queries.items():
        result = pd.read_sql_query(
            query,
            connection
        )

        output_path = (
            DASHBOARD_DATA_DIR
            / f"{query_name}.csv"
        )

        result.to_csv(
            output_path,
            index=False,
            encoding="utf-8-sig"
        )

        export_results.append(
            {
                "file_name": output_path.name,
                "row_count": len(result),
                "column_count": len(
                    result.columns
                )
            }
        )

    return pd.DataFrame(export_results)


def verify_dashboard_exports(export_results):
    """필수 대시보드 파일이 모두 생성됐는지 검사한다."""

    expected_files = {
        "dashboard_kpi.csv",
        "status_summary.csv",
        "error_type_summary.csv",
        "department_summary.csv",
        "transaction_type_summary.csv",
        "daily_summary.csv",
        "account_summary.csv",
        "partner_summary.csv",
        "review_detail.csv"
    }

    exported_files = set(
        export_results["file_name"]
    )

    missing_files = (
        expected_files
        - exported_files
    )

    if missing_files:
        raise FileNotFoundError(
            f"생성되지 않은 파일: "
            f"{sorted(missing_files)}"
        )

    # 핵심 파일이 비어 있지 않은지 확인
    empty_files = (
        export_results.loc[
            export_results["row_count"] == 0,
            "file_name"
        ]
        .tolist()
    )

    if empty_files:
        raise ValueError(
            f"데이터가 없는 파일: {empty_files}"
        )


def main():
    """대시보드용 데이터 내보내기를 실행한다."""

    print("대시보드 데이터 생성 시작")

    if not DATABASE_PATH.exists():
        raise FileNotFoundError(
            f"데이터베이스 없음: {DATABASE_PATH}"
        )

    # SQLite 데이터베이스 연결
    connection = sqlite3.connect(
        DATABASE_PATH
    )

    try:
        # 대시보드용 SQL 쿼리 준비
        queries = build_dashboard_queries()

        # SQL 실행 후 CSV 저장
        export_results = export_dashboard_data(
            connection,
            queries
        )

        # 생성 결과 검증
        verify_dashboard_exports(
            export_results
        )

        print()
        print("파일별 생성 결과")
        print(
            export_results.to_string(
                index=False
            )
        )

        print()
        print(
            "저장 위치:",
            DASHBOARD_DATA_DIR
        )

        print()
        print("대시보드 데이터 생성 완료")

    finally:
        connection.close()


if __name__ == "__main__":
    main()