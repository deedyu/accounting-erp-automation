"""검증 결과를 이용해 ERP 업로드 파일과 검토 대기열을 생성한다."""

import json
import pandas as pd
from typing import Any

# 기존 파일 직접 실행에서도 동일한 패키지 모듈을 사용한다.
if __name__ == "__main__" and not __package__:
    from _bootstrap import configure_script_imports

    configure_script_imports(__file__)

from src.journal_validator import PROJECT_ROOT
from src.journal_values import code, money, date_value, pair_columns


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
            ] != "입력 가능"
        ]
        .copy()
        .reset_index(drop=True)
    )

    # 상세 오류 유형의 열 이름을 명확하게 변경
    key = "_row_id" if "_row_id" in validation_result and "_row_id" in review_journal else "voucher_id"
    detail_columns = [key, "column", "error_type", "detail"] + [c for c in ["severity", "row_number"] if c in validation_result]
    validation_details = validation_result[detail_columns].rename(columns={"error_type": "error_type_detail", "row_number": "error_row_number"})
    review_journal[key] = review_journal[key].astype(object)
    validation_details[key] = validation_details[key].astype(object)
    review_queue = review_journal.merge(validation_details, on=key, how="left")

    return (
        ready_journal,
        review_queue
    )


ERP_COLUMNS = ["voucher_id", "line_no", "transaction_date", "transaction_type", "department_code", "partner_code",
               "debit_credit_type", "account_code", "account_name", "debit_amount", "credit_amount", "amount",
               "evidence_type", "evidence_no", "description", "remarks"]


def convert_to_erp_rows(ready_journal: pd.DataFrame, accounts: pd.DataFrame) -> pd.DataFrame:
    """정상 전표의 모든 계정 쌍을 날짜순 ERP 세로 분개로 변환한다."""
    names = {code(r.account_code): r.account_name for r in accounts.itertuples() if r.is_active == "Y"}
    erp_rows = []
    for _, row in ready_journal.iterrows():
        if row.get("processing_status", "입력 가능") != "입력 가능":
            continue
        line_no = 1
        for side, label in [("debit", "차변"), ("credit", "대변")]:
            for account_column, amount_column in pair_columns(ready_journal.columns, side):
                amount = money(row.get(amount_column))
                account = code(row.get(account_column))
                if amount in (None, 0):
                    continue
                if account not in names:
                    raise ValueError(f"ERP 변환 불가: 계정코드 {account}를 확인해 주세요.")
                record = {c: row.get(c) for c in ERP_COLUMNS}
                record.update(voucher_id=code(row.get("voucher_id")), line_no=line_no,
                              transaction_date=date_value(row.get("transaction_date")), account_code=account,
                              account_name=names[account], amount=amount, debit_credit_type=label,
                              debit_amount=amount if side == "debit" else 0, credit_amount=amount if side == "credit" else 0)
                erp_rows.append(record)
                line_no += 1
    return pd.DataFrame(erp_rows, columns=ERP_COLUMNS).sort_values(["transaction_date", "voucher_id", "line_no"], kind="stable").reset_index(drop=True)


def validate_erp_rows(erp_upload: pd.DataFrame, accounts: pd.DataFrame | None = None) -> tuple[pd.DataFrame, dict[str, int]]:
    """ERP 전표별 균형·순번·계정과 금액을 재검증한다."""
    if erp_upload.empty:
        return pd.DataFrame(columns=["voucher_id", "차변", "대변", "difference", "is_balanced"]), {"unbalanced_count": 0, "duplicate_line_count": 0, "unknown_account_count": 0}
    if erp_upload["voucher_id"].apply(code).eq("").any():
        raise ValueError("ERP 전표번호가 비어 있습니다.")
    if not erp_upload["debit_credit_type"].isin(["차변", "대변"]).all():
        raise ValueError("ERP 차대 구분이 올바르지 않습니다.")
    values = erp_upload["amount"].apply(money)
    if values.isna().any() or values.eq(0).any():
        raise ValueError("ERP 금액이 비어 있거나 0원입니다.")
    frame = erp_upload.copy()
    frame["amount"] = values
    for side, label in [("debit_amount", "차변"), ("credit_amount", "대변")]:
        if side in frame:
            expected = values.where(frame["debit_credit_type"].eq(label), 0)
            if not frame[side].apply(money).eq(expected).all():
                raise ValueError("ERP 차변·대변 금액과 분개 금액이 일치하지 않습니다.")
    balance = frame.pivot_table(index="voucher_id", columns="debit_credit_type", values="amount", aggfunc="sum", fill_value=0).reindex(columns=["차변", "대변"], fill_value=0).reset_index()
    balance.columns.name = None
    balance["difference"] = balance["차변"] - balance["대변"]
    balance["is_balanced"] = balance["difference"].eq(0)
    duplicates = int(frame.duplicated(["voucher_id", "line_no"]).sum())
    unknown = int(frame.account_name.eq("알 수 없음").sum())
    if accounts is not None:
        active = set(accounts.loc[accounts.is_active.eq("Y"), "account_code"].apply(code))
        unknown = int((~frame.account_code.apply(code).isin(active)).sum())
    if not balance.is_balanced.all() or duplicates or unknown:
        raise ValueError(f"ERP 재검증 실패: 차대 불일치 {int((~balance.is_balanced).sum())}건, 중복 순번 {duplicates}건, 계정 오류 {unknown}건")
    return balance, {"unbalanced_count": 0, "duplicate_line_count": duplicates, "unknown_account_count": unknown}


def build_erp_json(erp_upload):
    """세로형 ERP 데이터를 전표 단위의 중첩 JSON으로 변환한다."""

    erp_json_records = []

    # 전표번호별로 분개 행 묶기
    for voucher_id, voucher_group in (
        erp_upload.groupby(
            "voucher_id",
            sort=False
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
                    "account_code": code(line["account_code"]),
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
                "remarks": None if pd.isna(first_row["remarks"]) else first_row["remarks"],
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
    