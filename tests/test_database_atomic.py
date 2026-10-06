"""원본 보존과 실행 단위 DB 롤백 검사."""
from pathlib import Path
import sqlite3
import pandas as pd
import pytest
from src import adaptive_database as database
from src.adaptive_erp_export import run_full_pipeline


def test_missing_voucher_history_and_rollback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """전표번호 없는 오류도 저장하며 중간 실패 시 이전 실행만 남긴다."""
    source = tmp_path / "missing.xlsx"
    pd.DataFrame({"전표번호": [None], "거래일자": ["2026-08-01"], "적요": ["오류 전표"]}).to_excel(source, index=False)
    result = run_full_pipeline(source, output_directory=tmp_path / "results")
    path = tmp_path / "history.db"
    first = database.save_pipeline_to_database(result, database_path=path)
    assert len(database.list_runs(path)) == 1
    restored = database.load_run(first["run_id"], path)
    assert len(restored["classified_journal"]) == 1
    assert restored["classified_journal"].processing_status.tolist() == ["입력 불가"]
    original = database.insert_database_data

    def fail_midway(connection: sqlite3.Connection, rows: dict) -> None:
        """실행과 파일 저장 후 의도적으로 외래키 오류를 발생시킨다."""
        original(connection, {table: rows[table] for table in ["automation_runs", "automation_files"]})
        connection.execute("INSERT INTO automation_mappings(run_id,source_column,confidence,status) VALUES ('없는실행','열',100,'자동 확정')")

    monkeypatch.setattr(database, "insert_database_data", fail_midway)
    with pytest.raises(RuntimeError, match="실행 전체를 취소"):
        database.save_pipeline_to_database(result, database_path=path)
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM automation_runs").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM automation_files").fetchone()[0] == 1
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_existing_tables_preserved(tmp_path: Path) -> None:
    """기존 DB 테이블을 지우지 않고 새 이력 테이블을 추가한다."""
    path = tmp_path / "existing.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE original_data (value TEXT)")
        connection.execute("INSERT INTO original_data VALUES ('보존할 자료')")
        database.create_database_schema(connection)
        assert connection.execute("SELECT value FROM original_data").fetchall() == [("보존할 자료",)]
