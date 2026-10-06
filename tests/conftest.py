"""기존 샘플을 읽기 전용으로 사용하는 회귀 테스트 준비."""

from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from src.adaptive_pipeline import infer_accounting_period, load_master_data
from src.data_standardizer import standardize_excel_file
from src.journal_validator import (
    build_validation_standards,
    classify_transactions,
    validate_journal,
)
from src.prepare_erp_upload import convert_to_erp_rows, split_transactions


@pytest.fixture(scope="session")
def project_root() -> Path:
    """현재 프로젝트의 루트 경로를 반환한다."""
    return Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def baseline(project_root: Path) -> dict[str, Any]:
    """기존 500건 샘플을 파일 저장 없이 검증하고 변환한다."""
    standardization = standardize_excel_file(project_root / "data/raw/bulk_journal.xlsx")
    journal = standardization["dataframe"]
    accounts, vendors, departments = load_master_data()
    start, end = infer_accounting_period(journal)
    standards = build_validation_standards(accounts, vendors, departments, start, end)
    errors = validate_journal(journal, standards)
    classified = classify_transactions(journal, errors)
    ready, review = split_transactions(classified, errors)
    return {
        "journal": journal,
        "accounts": accounts,
        "standards": standards,
        "errors": errors,
        "classified": classified,
        "ready": ready,
        "review": review,
        "erp": convert_to_erp_rows(ready, accounts),
        "expected": pd.read_csv(project_root / "data/expected/bulk_injected_errors.csv"),
    }
