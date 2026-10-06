"""자동 표준화·검증 결과를 ERP 업로드 파일로 변환한다."""

from pathlib import Path
from typing import Any
import json
import sys

import pandas as pd

# 기존 파일 직접 실행에서도 동일한 패키지 모듈을 사용한다.
if __name__ == "__main__" and not __package__:
    from _bootstrap import configure_script_imports

    configure_script_imports(__file__)

from src.result_exporter import export_workbooks, clean_value
from src.adaptive_pipeline import (
    load_master_data,
    run_adaptive_pipeline
)
from src.prepare_erp_upload import (
    build_erp_json,
    convert_to_erp_rows,
    split_transactions,
    validate_erp_rows
)


def save_erp_results(
    output_directory,
    erp_upload,
    erp_json_records,
    review_queue,
    balance_check,
    erp_summary
):
    """
    ERP 변환 결과를 현재 업로드 파일의 결과 폴더에 저장한다.
    """
    output_directory = Path(output_directory)

    erp_csv_path = output_directory / "erp_upload.csv"
    erp_json_path = output_directory / "erp_upload.json"
    review_path = output_directory / "review_queue.csv"
    balance_path = output_directory / "erp_balance_check.csv"
    summary_path = output_directory / "erp_summary.csv"

    erp_upload.to_csv(
        erp_csv_path,
        index=False,
        encoding="utf-8-sig"
    )

    with open(
        erp_json_path,
        "w",
        encoding="utf-8"
    ) as json_file:
        json.dump(
            clean_value(erp_json_records),
            json_file,
            ensure_ascii=False,
            indent=2
        )

    review_queue.to_csv(
        review_path,
        index=False,
        encoding="utf-8-sig"
    )

    balance_check.to_csv(
        balance_path,
        index=False,
        encoding="utf-8-sig"
    )

    erp_summary.to_csv(
        summary_path,
        index=False,
        encoding="utf-8-sig"
    )

    return {
        "erp_csv": erp_csv_path,
        "erp_json": erp_json_path,
        "review_queue": review_path,
        "balance_check": balance_path,
        "erp_summary": summary_path
    }


def run_full_pipeline(
    file_path: str | Path,
    *,
    output_directory: str | Path | None = None,
    **options: Any,
) -> dict[str, Any]:
    """
    파일 분석부터 ERP CSV·JSON 생성까지 전체 과정을 실행한다.
    """
    print("\n자동 분개장 전체 처리 시작")

    # 자동 분석, 표준화와 회계 검증을 먼저 실행한다.
    pipeline_result = run_adaptive_pipeline(
        file_path, output_directory=output_directory, **options
    )

    classified_journal = pipeline_result[
        "classified_journal"
    ]
    validation_result = pipeline_result[
        "validation_result"
    ]
    output_directory = pipeline_result[
        "output_directory"
    ]

    print("\n9. 정상 전표와 검토 전표 분리")
    ready_journal, review_queue = split_transactions(
        classified_journal,
        validation_result
    )

    print("10. 정상 전표를 ERP 세로형 구조로 변환")
    accounts, _, _ = load_master_data()

    erp_upload = convert_to_erp_rows(
        ready_journal,
        accounts
    )

    print("11. ERP 변환 결과 재검증")
    balance_check, erp_validation = validate_erp_rows(
        erp_upload, accounts
    )

    print("12. ERP JSON 생성")
    erp_json_records = build_erp_json(
        erp_upload
    )

    erp_summary = pd.DataFrame(
        [
            {
                "ready_vouchers": int(
                    ready_journal["voucher_id"].nunique()
                ),
                "erp_journal_lines": len(erp_upload),
                "review_vouchers": int(
                    review_queue["voucher_id"].nunique()
                ),
                "review_errors": len(review_queue),
                "json_vouchers": len(erp_json_records),
                "unbalanced_vouchers": int(
                    (
                        balance_check["is_balanced"]
                        == False
                    ).sum()
                ),
                "duplicate_line_count": erp_validation[
                    "duplicate_line_count"
                ],
                "unknown_account_count": erp_validation[
                    "unknown_account_count"
                ]
            }
        ]
    )

    print("13. ERP 결과 저장")
    output_paths = save_erp_results(
        output_directory=output_directory,
        erp_upload=erp_upload,
        erp_json_records=erp_json_records,
        review_queue=review_queue,
        balance_check=balance_check,
        erp_summary=erp_summary
    )

    print("\nERP 자동 변환 완료")
    print(erp_summary.to_string(index=False))

    print("\n생성 파일")
    for file_type, file_path in output_paths.items():
        print(f"{file_type}: {file_path}")

    result = {
        **pipeline_result,
        "ready_journal": ready_journal,
        "review_queue": review_queue,
        "erp_upload": erp_upload,
        "erp_json_records": erp_json_records,
        "balance_check": balance_check,
        "erp_summary": erp_summary,
        "output_paths": output_paths
    }
    result["output_paths"].update(export_workbooks(result, accounts))
    return result


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(
            "사용 방법: "
            "python src/adaptive_erp_export.py 분개장파일.xlsx"
        )
        sys.exit(1)

    run_full_pipeline(sys.argv[1])
    