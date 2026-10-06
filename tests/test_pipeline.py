"""실제 파일 출력과 SQLite 이력 저장을 검증한다."""

import json
from pathlib import Path
import sqlite3

import pandas as pd
import pytest

from src.adaptive_database import run_and_save, save_pipeline_to_database
from src import run_pipeline


@pytest.mark.parametrize("filename", ["bulk_journal.xlsx", "journal_korean_headers.xlsx"])
def test_pipeline_writes_outputs_and_history(tmp_path: Path, project_root: Path, filename: str) -> None:
    """전체 처리 결과를 지정 경로에 저장하고 재실행 이력을 누적한다."""
    output = tmp_path / "results"
    database = tmp_path / "database/history.db"
    result = run_and_save(
        project_root / "data/raw" / filename,
        output_directory=output,
        database_path=database,
    )
    assert result["output_directory"] == output
    assert result["database_result"]["database_path"] == database
    assert result["database_result"]["foreign_key_errors"] == []
    assert all(path.is_file() for path in result["output_paths"].values())
    assert (output / "standardized_journal.xlsx").is_file()
    assert (output / "column_mapping.csv").is_file()
    csv = pd.read_csv(output / "erp_upload.csv")
    records = json.loads((output / "erp_upload.json").read_text())
    assert len(csv) == 1347
    assert len(records) == 449
    assert set(csv["voucher_id"]) == {record["voucher_id"] for record in records}
    assert csv["amount"].sum() == sum(line["amount"] for record in records for line in record["journal_lines"])
    second = save_pipeline_to_database(result, database_path=database)
    assert second["run_id"] != result["database_result"]["run_id"]
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        for table, expected in [("automation_runs", 2), ("automation_vouchers", 1000), ("automation_errors", 132), ("automation_erp_lines", 2694)]:
            assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == expected


def test_legacy_pipeline_stops_after_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """기존 CLI가 실패한 단계 이후 작업을 실행하지 않는다."""
    calls: list[str] = []

    def first() -> None:
        """첫 단계의 실행을 기록한다."""
        calls.append("first")

    def fail() -> None:
        """다음 단계의 실패를 재현한다."""
        calls.append("fail")
        raise ValueError("검증 실패")

    def last() -> None:
        """실행되면 안 되는 후속 단계를 기록한다."""
        calls.append("last")

    monkeypatch.setattr(run_pipeline, "PIPELINE_STEPS", [("첫 단계", first), ("실패 단계", fail), ("후속 단계", last)])
    with pytest.raises(ValueError, match="검증 실패"):
        run_pipeline.run_legacy_pipeline()
    assert calls == ["first", "fail"]
