"""검증 결과를 이용해 ERP 업로드 파일과 검토 대기열을 생성한다."""

import json
import pandas as pd

from journal_validator import PROJECT_ROOT


def load_processed_data():
    """검증이 완료된 전표 상태와 오류 결과를 불러온다."""

    transaction_status_path = (
        PROJECT_ROOT
        / "data"
        / "processed"
        / "bulk_transaction_status.csv"
    )

    validation_result_path = (
        PROJECT_ROOT
        / "data"
        / "processed"
        / "bulk_validation_result.csv"
    )

    accounts_path = (
        PROJECT_ROOT
        / "data"
        / "master"
        / "accounts.csv"
    )

    required_paths = [
        transaction_status_path,
        validation_result_path,
        accounts_path
    ]

    # 이전 검증 단계의 결과 파일이 있는지 확인
    for file_path in required_paths:
        if not file_path.exists():
            raise FileNotFoundError(
                f"필수 파일 없음: {file_path}"
            )

    transaction_status = pd.read_csv(
        transaction_status_path
    )

    validation_result = pd.read_csv(
        validation_result_path
    )

    accounts = pd.read_csv(
        accounts_path
    )

    return (
        transaction_status,
        validation_result,
        accounts
    )


def split_transactions(
    transaction_status,
    validation_result
):
    """전표를 ERP 입력 가능과 담당자 검토 필요로 분리한다."""

    # 오류가 없는 전표
    ready_journal = (
        transaction_status.loc[
            transaction_status[
                "processing_status"
            ] == "입력 가능"
        ]
        .copy()
        .reset_index(drop=True)
    )

    # 하나 이상의 오류가 있는 전표
    review_journal = (
        transaction_status.loc[
            transaction_status[
                "processing_status"
            ] == "검토 필요"
        ]
        .copy()
        .reset_index(drop=True)
    )

    # 상세 오류 유형의 열 이름을 명확하게 변경
    validation_details = (
        validation_result[
            [
                "voucher_id",
                "column",
                "error_type",
                "detail"
            ]
        ]
        .rename(
            columns={
                "error_type": "error_type_detail"
            }
        )
    )

    # 검토 전표에 오류 위치와 상세 사유 연결
    review_queue = review_journal.merge(
        validation_details,
        on="voucher_id",
        how="left"
    )

    return (
        ready_journal,
        review_queue
    )


def convert_to_erp_rows(
    ready_journal,
    accounts
):
    """가로형 정상 분개를 ERP 업로드용 세로형 구조로 변환한다."""

    # 계정코드로 계정과목명을 찾는 딕셔너리
    account_name_map = dict(
        zip(
            accounts["account_code"].astype(int),
            accounts["account_name"]
        )
    )

    erp_rows = []

    # 입력 가능한 전표를 한 건씩 변환
    for _, row in ready_journal.iterrows():
        line_no = 1

        debit_pairs = [
            (
                row["debit_account_1"],
                row["debit_amount_1"]
            ),
            (
                row["debit_account_2"],
                row["debit_amount_2"]
            )
        ]

        credit_pairs = [
            (
                row["credit_account_1"],
                row["credit_amount_1"]
            ),
            (
                row["credit_account_2"],
                row["credit_amount_2"]
            )
        ]

        # 차변 계정과 금액을 개별 행으로 추가
        for account_value, amount_value in debit_pairs:
            if (
                pd.isna(account_value)
                or pd.isna(amount_value)
                or amount_value == 0
            ):
                continue

            account_code = int(account_value)

            erp_rows.append(
                {
                    "voucher_id": row["voucher_id"],
                    "line_no": line_no,
                    "transaction_date": row[
                        "transaction_date"
                    ],
                    "transaction_type": row[
                        "transaction_type"
                    ],
                    "department_code": row[
                        "department_code"
                    ],
                    "partner_code": row[
                        "partner_code"
                    ],
                    "debit_credit_type": "차변",
                    "account_code": account_code,
                    "account_name": (
                        account_name_map.get(
                            account_code,
                            "알 수 없음"
                        )
                    ),
                    "amount": int(amount_value),
                    "evidence_type": row[
                        "evidence_type"
                    ],
                    "evidence_no": row[
                        "evidence_no"
                    ],
                    "description": row[
                        "description"
                    ],
                    "remarks": row["remarks"]
                }
            )

            line_no += 1

        # 대변 계정과 금액을 개별 행으로 추가
        for account_value, amount_value in credit_pairs:
            if (
                pd.isna(account_value)
                or pd.isna(amount_value)
                or amount_value == 0
            ):
                continue

            account_code = int(account_value)

            erp_rows.append(
                {
                    "voucher_id": row["voucher_id"],
                    "line_no": line_no,
                    "transaction_date": row[
                        "transaction_date"
                    ],
                    "transaction_type": row[
                        "transaction_type"
                    ],
                    "department_code": row[
                        "department_code"
                    ],
                    "partner_code": row[
                        "partner_code"
                    ],
                    "debit_credit_type": "대변",
                    "account_code": account_code,
                    "account_name": (
                        account_name_map.get(
                            account_code,
                            "알 수 없음"
                        )
                    ),
                    "amount": int(amount_value),
                    "evidence_type": row[
                        "evidence_type"
                    ],
                    "evidence_no": row[
                        "evidence_no"
                    ],
                    "description": row[
                        "description"
                    ],
                    "remarks": row["remarks"]
                }
            )

            line_no += 1

    return pd.DataFrame(erp_rows)


def validate_erp_rows(erp_upload):
    """ERP 변환 후 차변·대변과 데이터 구조를 재검증한다."""

    if erp_upload.empty:
        raise ValueError(
            "ERP 입력 가능 데이터가 없음"
        )

    # 전표별 차변·대변 금액 집계
    balance_check = (
        erp_upload
        .pivot_table(
            index="voucher_id",
            columns="debit_credit_type",
            values="amount",
            aggfunc="sum",
            fill_value=0
        )
        .reset_index()
    )

    balance_check.columns.name = None

    # 차변과 대변 차이 계산
    balance_check["difference"] = (
        balance_check["차변"]
        - balance_check["대변"]
    )

    balance_check["is_balanced"] = (
        balance_check["difference"] == 0
    )

    # 전표 내 순번 중복 검사
    duplicate_line_count = (
        erp_upload
        .duplicated(
            subset=[
                "voucher_id",
                "line_no"
            ]
        )
        .sum()
    )

    # 계정과목 연결 실패 검사
    unknown_account_count = (
        erp_upload["account_name"]
        == "알 수 없음"
    ).sum()

    # 검증 실패 전표
    unbalanced_count = (
        balance_check["is_balanced"]
        == False
    ).sum()

    # 잘못된 ERP 데이터가 있으면 저장 중단
    if unbalanced_count > 0:
        raise ValueError(
            f"차변·대변 불일치 전표: "
            f"{unbalanced_count}건"
        )

    if duplicate_line_count > 0:
        raise ValueError(
            f"전표 내 중복 순번: "
            f"{duplicate_line_count}건"
        )

    if unknown_account_count > 0:
        raise ValueError(
            f"알 수 없는 계정과목: "
            f"{unknown_account_count}건"
        )

    validation_summary = {
        "unbalanced_count": int(
            unbalanced_count
        ),
        "duplicate_line_count": int(
            duplicate_line_count
        ),
        "unknown_account_count": int(
            unknown_account_count
        )
    }

    return (
        balance_check,
        validation_summary
    )


def build_erp_json(erp_upload):
    """세로형 ERP 데이터를 전표 단위의 중첩 JSON으로 변환한다."""

    erp_json_records = []

    # 전표번호별로 분개 행 묶기
    for voucher_id, voucher_group in (
        erp_upload.groupby(
            "voucher_id",
            sort=True
        )
    ):
        first_row = voucher_group.iloc[0]

        journal_lines = []

        # 같은 전표의 차변·대변 행 생성
        for _, line in voucher_group.iterrows():
            journal_lines.append(
                {
                    "line_no": int(
                        line["line_no"]
                    ),
                    "debit_credit_type": line[
                        "debit_credit_type"
                    ],
                    "account_code": int(
                        line["account_code"]
                    ),
                    "account_name": line[
                        "account_name"
                    ],
                    "amount": int(line["amount"])
                }
            )

        # 전표 기본정보와 분개 행을 하나로 구성
        erp_json_records.append(
            {
                "voucher_id": voucher_id,
                "transaction_date": (
                    pd.to_datetime(
                        first_row[
                            "transaction_date"
                        ]
                    )
                    .strftime("%Y-%m-%d")
                ),
                "transaction_type": first_row[
                    "transaction_type"
                ],
                "department_code": first_row[
                    "department_code"
                ],
                "partner_code": first_row[
                    "partner_code"
                ],
                "evidence": {
                    "type": first_row[
                        "evidence_type"
                    ],
                    "number": first_row[
                        "evidence_no"
                    ]
                },
                "description": first_row[
                    "description"
                ],
                "remarks": first_row["remarks"],
                "journal_lines": journal_lines
            }
        )

    return erp_json_records


def save_erp_outputs(
    erp_upload,
    review_queue,
    balance_check,
    erp_json_records
):
    """ERP 업로드 데이터와 검토 대기열을 파일로 저장한다."""

    processed_dir = (
        PROJECT_ROOT
        / "data"
        / "processed"
    )

    outputs_dir = (
        PROJECT_ROOT
        / "outputs"
    )

    processed_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    outputs_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    erp_csv_path = (
        processed_dir
        / "bulk_erp_upload.csv"
    )

    erp_json_path = (
        processed_dir
        / "bulk_erp_upload.json"
    )

    review_queue_path = (
        processed_dir
        / "bulk_review_queue.csv"
    )

    balance_check_path = (
        processed_dir
        / "bulk_erp_balance_check.csv"
    )

    summary_path = (
        outputs_dir
        / "bulk_erp_upload_summary.csv"
    )

    # CSV 결과 저장
    erp_upload.to_csv(
        erp_csv_path,
        index=False,
        encoding="utf-8-sig"
    )

    review_queue.to_csv(
        review_queue_path,
        index=False,
        encoding="utf-8-sig"
    )

    balance_check.to_csv(
        balance_check_path,
        index=False,
        encoding="utf-8-sig"
    )

    # 중첩 JSON 저장
    with open(
        erp_json_path,
        "w",
        encoding="utf-8"
    ) as json_file:
        json.dump(
            erp_json_records,
            json_file,
            ensure_ascii=False,
            indent=2
        )

    # 처리 결과 요약 생성
    summary = pd.DataFrame(
        [
            {
                "ready_vouchers": (
                    erp_upload[
                        "voucher_id"
                    ].nunique()
                ),
                "erp_journal_lines": len(
                    erp_upload
                ),
                "review_vouchers": (
                    review_queue[
                        "voucher_id"
                    ].nunique()
                ),
                "review_errors": len(
                    review_queue
                ),
                "json_vouchers": len(
                    erp_json_records
                ),
                "unbalanced_vouchers": int(
                    (
                        balance_check[
                            "is_balanced"
                        ]
                        == False
                    ).sum()
                )
            }
        ]
    )

    summary.to_csv(
        summary_path,
        index=False,
        encoding="utf-8-sig"
    )

    return summary


def main():
    """ERP 업로드 데이터 생성 프로그램을 실행한다."""

    print("ERP 업로드 데이터 생성 시작")

    # 검증된 처리 상태와 기준정보 불러오기
    (
        transaction_status,
        validation_result,
        accounts
    ) = load_processed_data()

    print(
        f"전체 전표 수: "
        f"{len(transaction_status)}"
    )

    # 입력 가능과 검토 필요 전표 분리
    (
        ready_journal,
        review_queue
    ) = split_transactions(
        transaction_status,
        validation_result
    )

    print(
        f"입력 가능 전표: "
        f"{len(ready_journal)}"
    )

    print(
        f"검토 필요 전표: "
        f"{review_queue['voucher_id'].nunique()}"
    )

    # ERP 업로드용 세로형 분개 생성
    erp_upload = convert_to_erp_rows(
        ready_journal,
        accounts
    )

    print(
        f"변환된 ERP 분개 행: "
        f"{len(erp_upload)}"
    )

    # 변환 후 차변·대변 재검증
    (
        balance_check,
        validation_summary
    ) = validate_erp_rows(
        erp_upload
    )

    print(
        f"차변·대변 불일치: "
        f"{validation_summary['unbalanced_count']}"
    )

    print(
        f"중복 순번: "
        f"{validation_summary['duplicate_line_count']}"
    )

    print(
        f"계정 연결 실패: "
        f"{validation_summary['unknown_account_count']}"
    )

    # ERP용 중첩 JSON 생성
    erp_json_records = build_erp_json(
        erp_upload
    )

    # 최종 결과 저장
    summary = save_erp_outputs(
        erp_upload,
        review_queue,
        balance_check,
        erp_json_records
    )

    print()
    print("ERP 변환 결과")
    print(
        summary.to_string(
            index=False
        )
    )

    print()
    print("ERP 업로드 데이터 생성 완료")


if __name__ == "__main__":
    main()
    