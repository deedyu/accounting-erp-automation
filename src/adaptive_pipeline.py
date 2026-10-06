"""다양한 형식의 엑셀 분개장을 자동 표준화하고 검증하는 파이프라인."""

from pathlib import Path
from typing import Any
from uuid import uuid4
from datetime import datetime
import sys

import pandas as pd

# 기존 파일 직접 실행에서도 동일한 패키지 모듈을 사용한다.
if __name__ == "__main__" and not __package__:
    from _bootstrap import configure_script_imports

    configure_script_imports(__file__)

from src.data_standardizer import standardize_excel_file
from src.journal_values import date_value
from src.journal_validator import (
    build_validation_standards,
    classify_transactions,
    validate_journal, load_validation_rules
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MASTER_DIRECTORY = PROJECT_ROOT / "data" / "master"
PROCESSED_DIRECTORY = PROJECT_ROOT / "data" / "processed" / "adaptive"


def load_master_data():
    """
    계정과목, 거래처, 부서 기준정보를 불러온다.
    """
    accounts_path = MASTER_DIRECTORY / "accounts.csv"
    vendors_path = MASTER_DIRECTORY / "vendors.csv"
    departments_path = MASTER_DIRECTORY / "departments.csv"

    required_paths = [
        accounts_path,
        vendors_path,
        departments_path
    ]

    for file_path in required_paths:
        if not file_path.exists():
            raise FileNotFoundError(
                f"마스터 파일을 찾을 수 없습니다: {file_path}"
            )

    accounts = pd.read_csv(accounts_path, dtype={"account_code": str}, keep_default_na=False)
    vendors = pd.read_csv(vendors_path, dtype={"partner_code": str, "vendor_code": str}, keep_default_na=False)
    departments = pd.read_csv(departments_path, dtype={"department_code": str}, keep_default_na=False)

    return accounts, vendors, departments


def infer_accounting_period(journal):
    """
    거래일자가 가장 많이 포함된 연월을 회계기간 후보로 추정한다.
    추후 화면에서 사용자가 이 기간을 확인하거나 수정할 수 있다.
    """
    transaction_dates = pd.to_datetime(journal["transaction_date"].apply(date_value)).dropna()

    if transaction_dates.empty:
        today = pd.Timestamp.today().normalize()
        start = today.to_period("M").start_time
        return start, (start.to_period("M") + 1).start_time

    dominant_period = (
        transaction_dates
        .dt.to_period("M")
        .mode()
        .iloc[0]
    )

    period_start = dominant_period.start_time
    period_end = (dominant_period + 1).start_time

    return period_start, period_end


def build_summary(
    file_name,
    sheet_name,
    period_start,
    period_end,
    validation_result,
    classified_journal
):
    """
    자동 처리 결과를 대시보드와 보고서에서 사용할 요약표로 만든다.
    """
    ready_count = int(
        (
            classified_journal["processing_status"]
            == "입력 가능"
        ).sum()
    )

    review_count = int(
        (
            classified_journal["processing_status"]
            != "입력 가능"
        ).sum()
    )

    error_transaction_count = int(
        validation_result["_row_id"].nunique()
    )

    return pd.DataFrame(
        [
            {
                "source_file": file_name,
                "sheet_name": sheet_name,
                "period_start": period_start.date(),
                "period_end": period_end.date(),
                "total_transactions": len(classified_journal),
                "detected_errors": len(validation_result),
                "error_transactions": error_transaction_count,
                "ready_transactions": ready_count,
                "review_transactions": review_count,
                "warning_transactions": int(classified_journal.processing_status.eq("검토 필요").sum()),
                "blocked_transactions": int(classified_journal.processing_status.eq("입력 불가").sum()),
                "review_rate": round(
                    review_count
                    / len(classified_journal)
                    * 100,
                    2
                )
                if len(classified_journal) > 0
                else 0
            }
        ]
    )


def save_adaptive_results(
    source_file: str | Path,
    standardized_journal: pd.DataFrame,
    mapping_result: pd.DataFrame,
    validation_result: pd.DataFrame,
    classified_journal: pd.DataFrame,
    summary: pd.DataFrame,
    *,
    output_directory: str | Path | None = None,
) -> Path:
    """
    파일별 처리 결과를 별도 폴더에 저장한다.
    기존 bulk 결과 파일은 덮어쓰지 않는다.
    """
    source_stem = Path(source_file).stem
    output_directory = (
        Path(output_directory)
        if output_directory is not None
        else PROCESSED_DIRECTORY / source_stem / uuid4().hex
    )

    if output_directory.exists() and any(output_directory.iterdir()):
        raise FileExistsError("결과 폴더에 파일이 있습니다. 새 출력 폴더를 선택해 주세요.")
    output_directory.mkdir(parents=True, exist_ok=True)

    output_paths = {
        "standardized": (
            output_directory
            / "standardized_journal.xlsx"
        ),
        "mapping": (
            output_directory
            / "column_mapping.csv"
        ),
        "validation": (
            output_directory
            / "validation_errors.csv"
        ),
        "status": (
            output_directory
            / "transaction_status.csv"
        ),
        "summary": (
            output_directory
            / "processing_summary.csv"
        )
    }

    standardized_journal.to_excel(
        output_paths["standardized"],
        sheet_name="표준분개장",
        index=False
    )

    mapping_result.to_csv(
        output_paths["mapping"],
        index=False,
        encoding="utf-8-sig"
    )

    validation_result.to_csv(
        output_paths["validation"],
        index=False,
        encoding="utf-8-sig"
    )

    classified_journal.to_csv(
        output_paths["status"],
        index=False,
        encoding="utf-8-sig"
    )

    summary.to_csv(
        output_paths["summary"],
        index=False,
        encoding="utf-8-sig"
    )

    return output_directory


def run_adaptive_pipeline(
    file_path: str | Path,
    *,
    output_directory: str | Path | None = None,
    period_start: str | None = None, period_end: str | None = None,
    rules_path: str | Path | None = None,
    **options: Any,
) -> dict[str, Any]:
    """
    파일 분석부터 회계 오류 검증과 결과 저장까지 실행한다.
    """
    file_path = Path(file_path)

    print("\n1. 분개장 구조 분석 및 표준화")
    standardization_result = standardize_excel_file(
        file_path, **options
    )

    journal = standardization_result["dataframe"]
    mapping_result = standardization_result[
        "mapping_result"
    ]

    print("2. 마스터 데이터 불러오기")
    accounts, vendors, departments = load_master_data()

    print("3. 회계기간 자동 추정")
    inferred_start, inferred_end = infer_accounting_period(journal)
    period_start = pd.Timestamp(period_start) if period_start is not None else inferred_start
    period_end = pd.Timestamp(period_end) if period_end is not None else inferred_end
    if pd.isna(period_start) or pd.isna(period_end) or period_start >= period_end:
        raise ValueError("회계기간 시작일은 종료일보다 빨라야 합니다.")

    print(
        f"   추정 회계기간: "
        f"{period_start.date()} ~ "
        f"{period_end.date()}"
    )

    print("4. 회계 검증 기준 생성")
    standards = build_validation_standards(
        accounts=accounts,
        vendors=vendors,
        departments=departments,
        period_start=period_start,
        period_end=period_end
    )

    standards["rules"] = load_validation_rules(rules_path)

    print("5. 분개장 오류 검증")
    validation_result = validate_journal(
        journal,
        standards
    )

    print("6. 전표 처리 상태 분류")
    classified_journal = classify_transactions(
        journal,
        validation_result
    )

    print("7. 처리 결과 요약 생성")
    summary = build_summary(
        file_name=file_path.name,
        sheet_name=standardization_result["sheet_name"],
        period_start=period_start,
        period_end=period_end,
        validation_result=validation_result,
        classified_journal=classified_journal
    )

    print("8. 결과 파일 저장")
    output_directory = save_adaptive_results(
        source_file=file_path,
        standardized_journal=journal,
        mapping_result=mapping_result,
        validation_result=validation_result,
        classified_journal=classified_journal,
        summary=summary,
        output_directory=output_directory,
    )

    print("\n자동 분개장 처리 완료")
    print(summary.to_string(index=False))
    print(f"\n결과 폴더: {output_directory}")

    return {
        "standardization": standardization_result,
        "validation_result": validation_result,
        "classified_journal": classified_journal,
        "summary": summary,
        "output_directory": output_directory
    }


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(
            "사용 방법: "
            "python src/adaptive_pipeline.py 분개장파일.xlsx"
        )
        sys.exit(1)

    run_adaptive_pipeline(sys.argv[1])
    