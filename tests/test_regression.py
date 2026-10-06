"""검증·ERP 변환·집계의 기존 동작을 보존하는 테스트."""

from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from src.daily_ledger import (
    build_daily_balance_summary,
    build_monthly_balance_summary,
    build_side_by_side_ledger,
)
from src.data_standardizer import standardize_excel_file
from src.file_analyzer import analyze_excel_file
from src.journal_validator import compare_with_expected, validate_journal
from src.prepare_erp_upload import build_erp_json, validate_erp_rows


def test_existing_error_reference(baseline: dict[str, Any]) -> None:
    """주입 오류의 위치·유형과 전표 분류가 기존 기준과 일치한다."""
    _, metrics = compare_with_expected(baseline["errors"], baseline["expected"])
    assert metrics["correct_count"] == 50
    assert metrics["missed_count"] == 0
    assert len(baseline["errors"]) == 66
    assert len(baseline["journal"]) == 500
    assert len(baseline["ready"]) == 449
    assert baseline["review"]["voucher_id"].nunique() == 51
    assert set(baseline["review"]["voucher_id"]) >= set(baseline["expected"]["voucher_id"])


def test_erp_preserves_vouchers_and_amounts(baseline: dict[str, Any]) -> None:
    """검토 전표 제외와 전표별 원본 금액 보존을 확인한다."""
    erp = baseline["erp"]
    assert len(erp) == 1347
    assert set(erp["voucher_id"]) == set(baseline["ready"]["voucher_id"])
    assert not set(erp["voucher_id"]) & set(baseline["review"]["voucher_id"])
    balance, checks = validate_erp_rows(erp)
    assert balance["is_balanced"].all()
    assert all(value == 0 for value in checks.values())
    totals = erp.groupby(["voucher_id", "debit_credit_type"])["amount"].sum().unstack()
    source = baseline["ready"].set_index("voucher_id")["total_amount"].sort_index()
    for side in ["차변", "대변"]:
        pd.testing.assert_series_equal(totals[side].sort_index(), source, check_names=False, check_dtype=False)
    records = build_erp_json(erp)
    assert len(records) == 449
    assert sum(len(record["journal_lines"]) for record in records) == 1347
    assert {record["voucher_id"] for record in records} == set(source.index)


def test_daily_and_monthly_totals(baseline: dict[str, Any]) -> None:
    """일별 합계와 좌우표가 날짜가 유효한 원본 금액을 보존한다."""
    journal = baseline["classified"]
    daily = build_daily_balance_summary(journal)
    monthly = build_monthly_balance_summary(daily).iloc[0]
    ledger = build_side_by_side_ledger(journal, baseline["accounts"])
    valid = journal.loc[pd.to_datetime(journal["transaction_date"], errors="coerce").notna()]
    assert pd.Series(daily["transaction_date"]).is_monotonic_increasing
    assert ledger["transaction_date"].dropna().is_monotonic_increasing
    for side in ["debit", "credit"]:
        columns = [f"{side}_amount_1", f"{side}_amount_2"]
        expected = valid[columns].apply(pd.to_numeric).fillna(0).sum().sum()
        assert monthly[f"{side}_total"] == expected
        assert ledger[f"{side}_amount"].sum() == journal[columns].fillna(0).sum().sum()
    assert monthly["difference"] == monthly["debit_total"] - monthly["credit_total"]


@pytest.mark.parametrize("filename", ["bulk_journal.xlsx", "journal_korean_headers.xlsx"])
def test_sample_header_mapping(project_root: Path, baseline: dict[str, Any], filename: str) -> None:
    """영문·한글 샘플의 표준화 결과와 오류 목록이 일치한다."""
    path = project_root / "data/raw" / filename
    analysis = analyze_excel_file(path)
    result = standardize_excel_file(path)
    assert analysis["sheets"][result["sheet_name"]]["row_count"] == 500
    assert result["missing_columns"] == []
    pd.testing.assert_frame_equal(result["dataframe"], baseline["journal"])
    pd.testing.assert_frame_equal(validate_journal(result["dataframe"], baseline["standards"]), baseline["errors"])


@pytest.mark.parametrize("include_unknown", [False, True])
def test_reordered_korean_headers(
    tmp_path: Path, project_root: Path, baseline: dict[str, Any], include_unknown: bool,
) -> None:
    """다른 파일명·시트명·열 순서에서도 정확한 별칭은 처리한다."""
    source = pd.read_excel(project_root / "data/raw/journal_korean_headers.xlsx")
    if not include_unknown:
        source = source.drop(columns="작성자명")
    path = tmp_path / "다른_월별_분개장.xlsx"
    source[source.columns[::-1]].to_excel(path, sheet_name="업무자료", index=False)
    result = standardize_excel_file(path)
    assert result["sheet_name"] == "업무자료"
    assert result["missing_columns"] == []
    pd.testing.assert_frame_equal(result["dataframe"], baseline["journal"])
