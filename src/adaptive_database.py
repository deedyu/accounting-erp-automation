"""자동 분개장 처리 결과를 실행 이력별로 SQLite에 누적 저장한다."""

from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4
import sqlite3
import argparse
import json
from hashlib import sha256

import pandas as pd

# 기존 파일 직접 실행에서도 동일한 패키지 모듈을 사용한다.
if __name__ == "__main__" and not __package__:
    from _bootstrap import configure_script_imports

    configure_script_imports(__file__)

from src.adaptive_erp_export import run_full_pipeline
from src.result_exporter import clean_value, json_text
from src.journal_values import code, date_value
from src.settings import DATABASE_PATH


PROJECT_ROOT = Path(__file__).resolve().parents[1]

SCHEMA_PATH = (
    PROJECT_ROOT
    / "sql"
    / "history_schema.sql"
)


def create_run_id():
    """
    처리 시각과 임의 식별자를 조합하여 실행별 고유 ID를 만든다.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    random_code = uuid4().hex[:8]

    return f"{timestamp}_{random_code}"


def create_database_schema(connection):
    """
    자동화용 테이블과 인덱스를 생성한다.
    """
    if not SCHEMA_PATH.exists():
        raise FileNotFoundError(
            f"DB 설계 파일을 찾을 수 없습니다: {SCHEMA_PATH}"
        )

    with open(
        SCHEMA_PATH,
        "r",
        encoding="utf-8"
    ) as schema_file:
        connection.executescript(
            schema_file.read()
        )


TABLES = ["automation_runs", "automation_files", "automation_mappings", "automation_vouchers", "automation_errors", "automation_erp_lines", "automation_daily_totals"]


def prepare_database_data(pipeline_result: dict[str, Any], run_id: str) -> dict[str, list[dict[str, Any]]]:
    """원본·검증·ERP·집계 자료를 내부 식별자로 연결해 저장 행을 구성한다."""
    result = pipeline_result
    standard = result["standardization"]
    summary = result["summary"].iloc[0].to_dict()
    snapshot = {key: result[key].to_dict("records") for key in ["daily_ledger", "daily_summary", "ready_daily_summary", "monthly_summary", "ready_monthly_summary", "erp_summary"]}
    paths = {key: str(value) for key, value in result["output_paths"].items()}
    data = {table: [] for table in TABLES}
    data["automation_runs"] = [{"run_id": run_id, "processed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source_file": standard["file_name"], "sheet_name": standard["sheet_name"], "summary_json": json_text(summary),
        "output_paths_json": json_text(paths), "snapshot_json": json_text(snapshot)}]
    options = {key: standard[key] for key in ["sheet_name", "header_row", "data_start", "data_end", "layout"]}
    data["automation_files"] = [{"run_id": run_id, "source_hash": result.get("source_hash", ""), "source_name": standard["file_name"],
        "options_json": json_text(options), "raw_json": json_text(standard["raw_dataframe"].to_dict("split")),
        "unmapped_json": json_text(standard["unmapped_data"].to_dict("split")), "excluded_json": json_text(standard["excluded_rows"].to_dict("split"))}]
    for mapping in standard["mapping_result"].to_dict("records"):
        data["automation_mappings"].append({"run_id": run_id, **mapping})
    voucher_map = {}
    for row in result["classified_journal"].to_dict("records"):
        voucher_map[code(row["voucher_id"])] = row["_row_id"]
        data["automation_vouchers"].append({"run_id": run_id, "row_id": row["_row_id"], "voucher_id": code(row["voucher_id"]) or None,
            "row_number": row["row_number"], "transaction_date": clean_value(date_value(row["transaction_date"])),
            "processing_status": row["processing_status"], "payload_json": json_text(row)})
    for row in result["validation_result"].to_dict("records"):
        data["automation_errors"].append({"run_id": run_id, "row_id": row["_row_id"], "voucher_id": code(row["voucher_id"]) or None,
            "row_number": row["row_number"], "error_column": row["column"], "error_type": row["error_type"], "severity": row["severity"], "detail": row["detail"]})
    for row in result["erp_upload"].to_dict("records"):
        data["automation_erp_lines"].append({"run_id": run_id, "row_id": voucher_map[code(row["voucher_id"])],
            **{key: row[key] for key in ["voucher_id", "line_no", "transaction_date", "account_code", "debit_amount", "credit_amount", "amount"]},
            "payload_json": json_text(row)})
    for scope, key in [("전체", "daily_summary"), ("정상", "ready_daily_summary")]:
        for row in result[key].to_dict("records"):
            data["automation_daily_totals"].append({"run_id": run_id, "scope": scope, **row})
    return clean_value(data)


def insert_database_data(connection: sqlite3.Connection, database_data: dict[str, list[dict[str, Any]]]) -> None:
    """호출자의 트랜잭션 안에서만 모든 실행 데이터를 삽입한다."""
    for table in TABLES:
        for row in database_data.get(table, []):
            columns = list(row)
            names = ", ".join(f'"{c}"' for c in columns)
            placeholders = ", ".join("?" for _ in columns)
            connection.execute(f'INSERT INTO "{table}" ({names}) VALUES ({placeholders})', [row[c] for c in columns])


def verify_saved_run(connection: sqlite3.Connection, run_id: str) -> tuple[pd.DataFrame, list]:
    """실행별 건수와 외래키 무결성을 검사한다."""
    rows = [{"table_name": table, "row_count": connection.execute(f'SELECT COUNT(*) FROM "{table}" WHERE run_id=?', (run_id,)).fetchone()[0]} for table in TABLES]
    return pd.DataFrame(rows), connection.execute("PRAGMA foreign_key_check").fetchall()


def save_pipeline_to_database(
    pipeline_result: dict[str, Any],
    *,
    database_path: str | Path | None = None,
) -> dict[str, Any]:
    """
    파이프라인 결과에 실행 ID를 부여하고 DB에 누적 저장한다.
    """
    database_path = Path(database_path) if database_path is not None else DATABASE_PATH
    run_id = create_run_id()

    database_data = prepare_database_data(
        pipeline_result,
        run_id
    )

    database_path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    connection = sqlite3.connect(
        database_path
    )

    try:
        connection.execute(
            "PRAGMA foreign_keys = ON"
        )

        create_database_schema(connection)

        with connection:
            insert_database_data(
                connection,
                database_data
            )

            table_counts, foreign_key_errors = verify_saved_run(connection, run_id)
            if foreign_key_errors:
                raise sqlite3.IntegrityError("외래키 무결성 검사에 실패했습니다.")

    except sqlite3.Error as error:
        raise RuntimeError(f"SQLite 저장 실패: 실행 전체를 취소했습니다. {error}") from error
    finally:
        connection.close()

    return {
        "run_id": run_id,
        "table_counts": table_counts,
        "foreign_key_errors": foreign_key_errors,
        "database_path": database_path
    }


def run_and_save(
    file_path: str | Path,
    *,
    output_directory: str | Path | None = None,
    database_path: str | Path | None = None,
    **options: Any,
) -> dict[str, Any]:
    """
    자동 분석부터 ERP 변환과 DB 누적 저장까지 실행한다.
    """
    pipeline_result = run_full_pipeline(
        file_path, output_directory=output_directory, **options
    )

    pipeline_result["source_hash"] = sha256(Path(file_path).read_bytes()).hexdigest()
    print("\n14. SQLite 실행 이력 저장")

    database_result = save_pipeline_to_database(
        pipeline_result, database_path=database_path
    )

    print(f"\n실행 ID: {database_result['run_id']}")

    print("\n테이블별 저장 건수")
    print(
        database_result["table_counts"].to_string(
            index=False
        )
    )

    print(
        "\n외래키 오류 수:",
        len(database_result["foreign_key_errors"])
    )

    print(
        "DB 저장 위치:",
        database_result["database_path"]
    )

    return {
        **pipeline_result,
        "database_result": database_result
    }


def list_runs(database_path: str | Path = DATABASE_PATH) -> pd.DataFrame:
    """기존 데이터 변경 없이 최근 실행 이력을 조회한다."""
    path = Path(database_path)
    if not path.exists():
        return pd.DataFrame()
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as connection:
        names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "automation_runs" in names:
            return pd.read_sql_query("SELECT run_id, processed_at, source_file, sheet_name, summary_json FROM automation_runs ORDER BY processed_at DESC, rowid DESC LIMIT 200", connection)
        if "processing_runs" in names:
            return pd.read_sql_query("SELECT * FROM processing_runs ORDER BY processed_at DESC LIMIT 200", connection)
    return pd.DataFrame()


def load_run(run_id: str, database_path: str | Path = DATABASE_PATH) -> dict[str, Any]:
    """저장된 실행 결과를 대시보드에서 다시 조회할 수 있게 복원한다."""
    with sqlite3.connect(Path(database_path).resolve().as_uri() + "?mode=ro", uri=True) as connection:
        row = connection.execute("SELECT summary_json, output_paths_json, snapshot_json FROM automation_runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise ValueError("선택한 실행 이력을 찾을 수 없습니다.")
        result = {key: pd.DataFrame(value) for key, value in json.loads(row[2]).items()}
        result["summary"] = pd.DataFrame([json.loads(row[0])])
        result["output_paths"] = {key: Path(value) for key, value in json.loads(row[1]).items()}
        for key, table in [("classified_journal", "automation_vouchers"), ("erp_upload", "automation_erp_lines")]:
            rows = connection.execute(f"SELECT payload_json FROM {table} WHERE run_id=? ORDER BY rowid", (run_id,)).fetchall()
            result[key] = pd.DataFrame([json.loads(r[0]) for r in rows])
        result["validation_result"] = pd.read_sql_query("SELECT voucher_id, row_number, error_column AS 'column', error_type, severity, detail, row_id AS _row_id FROM automation_errors WHERE run_id=?", connection, params=(run_id,))
        result["database_result"] = {"run_id": run_id, "database_path": Path(database_path)}
        return result


def main(argv: list[str] | None = None) -> None:
    """입력 파일과 선택 저장 경로를 받아 전체 파이프라인을 실행한다."""
    parser = argparse.ArgumentParser(description="분개장 검증·ERP 변환·SQLite 저장")
    parser.add_argument("file_path", type=Path, help="분석할 분개장 Excel 파일")
    parser.add_argument("--output-dir", type=Path, help="결과 파일을 저장할 폴더")
    parser.add_argument("--database-path", type=Path, help="실행 이력을 저장할 SQLite 경로")
    parser.add_argument("--sheet", help="처리할 시트명")
    parser.add_argument("--header-row", type=int, help="Excel 헤더 행 번호(1부터)")
    parser.add_argument("--data-start", type=int, help="첫 데이터 행 번호(1부터)")
    parser.add_argument("--data-end", type=int, help="마지막 데이터 행 번호(포함)")
    parser.add_argument("--layout", choices=["auto", "wide", "vertical"], default="auto")
    parser.add_argument("--period-start", help="회계기간 시작일")
    parser.add_argument("--period-end", help="회계기간 종료일(미포함)")
    args = parser.parse_args(argv)
    run_and_save(
        args.file_path,
        output_directory=args.output_dir,
        database_path=args.database_path, sheet_name=args.sheet,
        header_row=args.header_row - 1 if args.header_row is not None else None,
        data_start=args.data_start, data_end=args.data_end, layout=args.layout,
        period_start=args.period_start, period_end=args.period_end,
    )


if __name__ == "__main__":
    main()
