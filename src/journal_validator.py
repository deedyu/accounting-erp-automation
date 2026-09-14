"""회계 분개장의 입력 오류를 검증하고 처리 상태를 분류하는 프로그램."""

import pandas as pd
from pathlib import Path


# 현재 파일의 상위 프로젝트 폴더
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def is_missing(value):
    """결측값 또는 공백만 있는 문자열인지 확인한다."""

    return (
        pd.isna(value)
        or str(value).strip() == ""
    )


def add_error(
    error_list,
    voucher_id,
    column,
    error_type,
    detail
):
    """탐지한 오류를 동일한 구조로 목록에 추가한다."""

    error_list.append(
        {
            "voucher_id": voucher_id,
            "column": column,
            "error_type": error_type,
            "detail": detail
        }
    )


def load_project_data(journal_filename):
    """
    마스터 데이터와 검증 대상 분개장을 불러온다.

    Parameters
    ----------
    journal_filename : str
        data/raw 폴더에 저장된 엑셀 파일명

    Returns
    -------
    tuple
        계정과목, 거래처, 부서, 분개장 데이터프레임
    """

    accounts_path = (
        PROJECT_ROOT
        / "data"
        / "master"
        / "accounts.csv"
    )

    vendors_path = (
        PROJECT_ROOT
        / "data"
        / "master"
        / "vendors.csv"
    )

    departments_path = (
        PROJECT_ROOT
        / "data"
        / "master"
        / "departments.csv"
    )

    journal_path = (
        PROJECT_ROOT
        / "data"
        / "raw"
        / journal_filename
    )

    # 프로그램 실행에 필요한 파일 목록
    required_paths = [
        accounts_path,
        vendors_path,
        departments_path,
        journal_path
    ]

    # 파일이 없으면 검증 시작 전 명확한 오류 발생
    for file_path in required_paths:
        if not file_path.exists():
            raise FileNotFoundError(
                f"필수 파일 없음: {file_path}"
            )

    # 마스터 데이터 불러오기
    accounts = pd.read_csv(accounts_path)
    vendors = pd.read_csv(vendors_path)
    departments = pd.read_csv(departments_path)

    # 검증 대상 분개장 불러오기
    journal = pd.read_excel(
        journal_path,
        sheet_name="분개장"
    )

    return (
        accounts,
        vendors,
        departments,
        journal
    )


def build_validation_standards(
    accounts,
    vendors,
    departments,
    period_start,
    period_end
):
    """마스터 데이터와 회계기간을 검증 기준으로 변환한다."""

    # 사용 중인 계정과목 코드
    valid_account_codes = set(
        accounts.loc[
            accounts["is_active"] == "Y",
            "account_code"
        ]
        .dropna()
        .astype(int)
    )

    # 사용 중인 거래처 코드
    valid_partner_codes = set(
        vendors.loc[
            vendors["is_active"] == "Y",
            "partner_code"
        ]
        .dropna()
        .astype(str)
    )

    # 사용 중인 부서 코드
    valid_department_codes = set(
        departments.loc[
            departments["is_active"] == "Y",
            "department_code"
        ]
        .dropna()
        .astype(str)
    )

    return {
        "valid_account_codes": valid_account_codes,
        "valid_partner_codes": valid_partner_codes,
        "valid_department_codes": valid_department_codes,
        "period_start": pd.Timestamp(period_start),
        "period_end": pd.Timestamp(period_end)
    }


def validate_journal(journal, standards):
    """
    분개장의 필수값, 마스터 코드, 회계금액,
    부가세, 증빙번호 및 회계기간을 검사한다.
    """

    valid_account_codes = standards[
        "valid_account_codes"
    ]

    valid_partner_codes = standards[
        "valid_partner_codes"
    ]

    valid_department_codes = standards[
        "valid_department_codes"
    ]

    period_start = standards["period_start"]
    period_end = standards["period_end"]

    detected_errors = []

    # 반드시 값이 입력되어야 하는 열
    required_columns = [
        "voucher_id",
        "transaction_date",
        "department_code",
        "partner_code",
        "evidence_type",
        "evidence_no",
        "description",
        "debit_account_1",
        "debit_amount_1",
        "credit_account_1",
        "credit_amount_1",
        "supply_amount",
        "vat_amount",
        "total_amount"
    ]

    # 계정과목 코드가 들어 있는 열
    account_columns = [
        "debit_account_1",
        "debit_account_2",
        "credit_account_1",
        "credit_account_2"
    ]

    # 비어 있지 않은 증빙번호만 중복 검사
    valid_evidence_mask = journal[
        "evidence_no"
    ].apply(
        lambda value: not is_missing(value)
    )

    # 같은 증빙번호의 두 번째 등장부터 중복 처리
    duplicate_evidence_mask = (
        valid_evidence_mask
        & journal["evidence_no"].duplicated(
            keep="first"
        )
    )

    # 분개장 거래를 한 행씩 검사
    for row_index, row in journal.iterrows():
        voucher_id = row["voucher_id"]

        # 필수값 누락 검사
        for column in required_columns:
            if is_missing(row[column]):
                add_error(
                    error_list=detected_errors,
                    voucher_id=voucher_id,
                    column=column,
                    error_type="필수값 누락",
                    detail=f"{column}: 값 누락"
                )

        # 거래처 코드 검사
        if not is_missing(row["partner_code"]):
            partner_code = str(
                row["partner_code"]
            )

            if (
                partner_code
                not in valid_partner_codes
            ):
                add_error(
                    error_list=detected_errors,
                    voucher_id=voucher_id,
                    column="partner_code",
                    error_type="존재하지 않는 거래처",
                    detail=(
                        f"{partner_code}: "
                        "거래처 기준표에 없음"
                    )
                )

        # 부서 코드 검사
        if not is_missing(row["department_code"]):
            department_code = str(
                row["department_code"]
            )

            if (
                department_code
                not in valid_department_codes
            ):
                add_error(
                    error_list=detected_errors,
                    voucher_id=voucher_id,
                    column="department_code",
                    error_type="존재하지 않는 부서",
                    detail=(
                        f"{department_code}: "
                        "부서 기준표에 없음"
                    )
                )

        # 차변·대변 계정과목 코드 검사
        for column in account_columns:
            account_value = row[column]

            # 사용하지 않는 두 번째 계정은 검사 제외
            if is_missing(account_value):
                continue

            numeric_account = pd.to_numeric(
                account_value,
                errors="coerce"
            )

            if (
                pd.isna(numeric_account)
                or int(numeric_account)
                not in valid_account_codes
            ):
                add_error(
                    error_list=detected_errors,
                    voucher_id=voucher_id,
                    column=column,
                    error_type="존재하지 않는 계정과목",
                    detail=(
                        f"{account_value}: "
                        "계정과목 기준표에 없음"
                    )
                )

        # 금액 열을 숫자로 변환
        debit_amount_1 = pd.to_numeric(
            row["debit_amount_1"],
            errors="coerce"
        )

        debit_amount_2 = pd.to_numeric(
            row["debit_amount_2"],
            errors="coerce"
        )

        credit_amount_1 = pd.to_numeric(
            row["credit_amount_1"],
            errors="coerce"
        )

        credit_amount_2 = pd.to_numeric(
            row["credit_amount_2"],
            errors="coerce"
        )

        total_amount = pd.to_numeric(
            row["total_amount"],
            errors="coerce"
        )

        supply_amount = pd.to_numeric(
            row["supply_amount"],
            errors="coerce"
        )

        vat_amount = pd.to_numeric(
            row["vat_amount"],
            errors="coerce"
        )

        # 사용하지 않는 금액 열은 0으로 처리
        debit_amount_1 = (
            0
            if pd.isna(debit_amount_1)
            else debit_amount_1
        )

        debit_amount_2 = (
            0
            if pd.isna(debit_amount_2)
            else debit_amount_2
        )

        credit_amount_1 = (
            0
            if pd.isna(credit_amount_1)
            else credit_amount_1
        )

        credit_amount_2 = (
            0
            if pd.isna(credit_amount_2)
            else credit_amount_2
        )

        # 차변과 대변 합계 계산
        debit_total = (
            debit_amount_1
            + debit_amount_2
        )

        credit_total = (
            credit_amount_1
            + credit_amount_2
        )

        # 차변·대변 불일치 검사
        if debit_total != credit_total:
            add_error(
                error_list=detected_errors,
                voucher_id=voucher_id,
                column="debit_amount_1",
                error_type="차변·대변 불일치",
                detail=(
                    f"차변 {debit_total:,.0f}원 / "
                    f"대변 {credit_total:,.0f}원"
                )
            )

        # 차변·대변이 같을 때 총금액 검사
        elif (
            not pd.isna(total_amount)
            and total_amount != debit_total
        ):
            add_error(
                error_list=detected_errors,
                voucher_id=voucher_id,
                column="total_amount",
                error_type="전표 합계 불일치",
                detail=(
                    f"입력 {total_amount:,.0f}원 / "
                    f"분개 {debit_total:,.0f}원"
                )
            )

        # 일반 과세 거래의 부가세 검사
        if (
            not pd.isna(supply_amount)
            and supply_amount > 0
            and not pd.isna(vat_amount)
        ):
            expected_vat = round(
                supply_amount * 0.1
            )

            if vat_amount != expected_vat:
                add_error(
                    error_list=detected_errors,
                    voucher_id=voucher_id,
                    column="vat_amount",
                    error_type="부가세 계산 오류",
                    detail=(
                        f"입력 {vat_amount:,.0f}원 / "
                        f"예상 {expected_vat:,.0f}원"
                    )
                )

        # 중복 증빙번호 검사
        if duplicate_evidence_mask.loc[row_index]:
            add_error(
                error_list=detected_errors,
                voucher_id=voucher_id,
                column="evidence_no",
                error_type="증빙번호 중복",
                detail=(
                    f"{row['evidence_no']}: "
                    "중복 증빙"
                )
            )

        # 거래일자를 날짜로 변환
        transaction_date = pd.to_datetime(
            row["transaction_date"],
            errors="coerce"
        )

        # 날짜 형식 오류 검사
        if (
            not is_missing(row["transaction_date"])
            and pd.isna(transaction_date)
        ):
            add_error(
                error_list=detected_errors,
                voucher_id=voucher_id,
                column="transaction_date",
                error_type="날짜 형식 오류",
                detail=(
                    f"{row['transaction_date']}: "
                    "날짜 변환 불가"
                )
            )

        # 회계기간 이탈 검사
        elif not pd.isna(transaction_date):
            if not (
                period_start
                <= transaction_date
                < period_end
            ):
                add_error(
                    error_list=detected_errors,
                    voucher_id=voucher_id,
                    column="transaction_date",
                    error_type="회계기간 이탈",
                    detail=(
                        f"{transaction_date.date()}: "
                        "회계기간 아님"
                    )
                )

    # 오류가 없어도 동일한 열 구조로 생성
    validation_result = pd.DataFrame(
        detected_errors,
        columns=[
            "voucher_id",
            "column",
            "error_type",
            "detail"
        ]
    )

    # 전표번호와 오류 유형 순서로 정렬
    if not validation_result.empty:
        validation_result = (
            validation_result
            .sort_values(
                by=[
                    "voucher_id",
                    "error_type"
                ]
            )
            .reset_index(drop=True)
        )

    return validation_result


def compare_with_expected(
    validation_result,
    expected_errors
):
    """탐지 결과를 오류 정답표와 비교한다."""

    # 성능 비교에 필요한 열만 선택
    expected_keys = expected_errors[
        [
            "voucher_id",
            "column",
            "error_type"
        ]
    ].copy()

    detected_keys = validation_result[
        [
            "voucher_id",
            "column",
            "error_type",
            "detail"
        ]
    ].copy()

    # 정답과 탐지 결과를 모두 유지하며 병합
    comparison = expected_keys.merge(
        detected_keys,
        on=[
            "voucher_id",
            "column",
            "error_type"
        ],
        how="outer",
        indicator=True
    )

    # 병합 상태를 이해하기 쉬운 이름으로 변경
    comparison["comparison_status"] = (
        comparison["_merge"].map(
            {
                "both": "정상 탐지",
                "left_only": "미탐지",
                "right_only": "추가 탐지"
            }
        )
    )

    comparison = comparison.drop(
        columns="_merge"
    )

    # 성능 계산
    correct_count = (
        comparison["comparison_status"]
        == "정상 탐지"
    ).sum()

    missed_count = (
        comparison["comparison_status"]
        == "미탐지"
    ).sum()

    unexpected_count = (
        comparison["comparison_status"]
        == "추가 탐지"
    ).sum()

    recall = (
        correct_count
        / (correct_count + missed_count)
        if correct_count + missed_count > 0
        else 0
    )

    precision = (
        correct_count
        / (correct_count + unexpected_count)
        if correct_count + unexpected_count > 0
        else 0
    )

    metrics = {
        "correct_count": int(correct_count),
        "missed_count": int(missed_count),
        "unexpected_count": int(
            unexpected_count
        ),
        "precision": precision,
        "recall": recall
    }

    return comparison, metrics


def classify_transactions(
    journal,
    validation_result
):
    """오류 유무에 따라 전표의 처리 상태를 분류한다."""

    # 전표별 오류 개수와 오류 유형 집계
    error_summary = (
        validation_result
        .groupby("voucher_id")
        .agg(
            error_count=(
                "error_type",
                "count"
            ),
            error_types=(
                "error_type",
                lambda values: ", ".join(
                    sorted(set(values))
                )
            )
        )
        .reset_index()
    )

    # 원본 분개장에 오류 집계 결과 연결
    classified_journal = journal.merge(
        error_summary,
        on="voucher_id",
        how="left"
    )

    # 오류가 없는 전표의 결측값 처리
    classified_journal["error_count"] = (
        classified_journal["error_count"]
        .fillna(0)
        .astype(int)
    )

    classified_journal["error_types"] = (
        classified_journal["error_types"]
        .fillna("없음")
    )

    # 오류 개수에 따라 처리 상태 결정
    classified_journal["processing_status"] = (
        classified_journal["error_count"]
        .apply(
            lambda count: (
                "입력 가능"
                if count == 0
                else "검토 필요"
            )
        )
    )

    return classified_journal


def save_results(
    validation_result,
    comparison,
    classified_journal,
    metrics
):
    """검증 결과와 처리 상태를 CSV로 저장한다."""

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

    # 결과 파일 경로
    validation_path = (
        processed_dir
        / "bulk_validation_result.csv"
    )

    comparison_path = (
        processed_dir
        / "bulk_validation_comparison.csv"
    )

    status_path = (
        processed_dir
        / "bulk_transaction_status.csv"
    )

    summary_path = (
        outputs_dir
        / "bulk_validation_summary.csv"
    )

    # 성능 요약표 생성
    summary = pd.DataFrame(
        [
            {
                "total_transactions": len(
                    classified_journal
                ),
                "detected_errors": len(
                    validation_result
                ),
                "correct_detections": metrics[
                    "correct_count"
                ],
                "missed_errors": metrics[
                    "missed_count"
                ],
                "unexpected_detections": metrics[
                    "unexpected_count"
                ],
                "precision": metrics["precision"],
                "recall": metrics["recall"],
                "ready_transactions": int(
                    (
                        classified_journal[
                            "processing_status"
                        ]
                        == "입력 가능"
                    ).sum()
                ),
                "review_transactions": int(
                    (
                        classified_journal[
                            "processing_status"
                        ]
                        == "검토 필요"
                    ).sum()
                )
            }
        ]
    )

    # 결과 파일 저장
    validation_result.to_csv(
        validation_path,
        index=False,
        encoding="utf-8-sig"
    )

    comparison.to_csv(
        comparison_path,
        index=False,
        encoding="utf-8-sig"
    )

    classified_journal.to_csv(
        status_path,
        index=False,
        encoding="utf-8-sig"
    )

    summary.to_csv(
        summary_path,
        index=False,
        encoding="utf-8-sig"
    )

    return {
        "validation_path": validation_path,
        "comparison_path": comparison_path,
        "status_path": status_path,
        "summary_path": summary_path,
        "summary": summary
    }


def main():
    """500건 합성 분개장 검증 프로그램을 실행한다."""

    print("분개장 검증 시작")

    # 대규모 분개장과 마스터 데이터 불러오기
    (
        accounts,
        vendors,
        departments,
        journal
    ) = load_project_data(
        "bulk_journal.xlsx"
    )

    print(f"불러온 거래 수: {len(journal)}")

    # 2026년 8월 기준 검증 규칙 생성
    standards = build_validation_standards(
        accounts=accounts,
        vendors=vendors,
        departments=departments,
        period_start="2026-08-01",
        period_end="2026-09-01"
    )

    # 전체 오류 검증 실행
    validation_result = validate_journal(
        journal=journal,
        standards=standards
    )

    print(
        f"탐지한 오류 수: {len(validation_result)}"
    )

    # 오류 정답표 불러오기
    expected_errors_path = (
        PROJECT_ROOT
        / "data"
        / "expected"
        / "bulk_injected_errors.csv"
    )

    if not expected_errors_path.exists():
        raise FileNotFoundError(
            f"오류 정답표 없음: {expected_errors_path}"
        )

    expected_errors = pd.read_csv(
        expected_errors_path
    )

    # 탐지 결과와 정답 비교
    comparison, metrics = (
        compare_with_expected(
            validation_result,
            expected_errors
        )
    )

    # 전표별 처리 상태 분류
    classified_journal = (
        classify_transactions(
            journal,
            validation_result
        )
    )

    # 검증 결과 저장
    saved_results = save_results(
        validation_result,
        comparison,
        classified_journal,
        metrics
    )

    print(
        f"정상 탐지: "
        f"{metrics['correct_count']}"
    )
    print(
        f"미탐지: "
        f"{metrics['missed_count']}"
    )
    print(
        f"추가 탐지: "
        f"{metrics['unexpected_count']}"
    )
    print(
        f"정밀도: "
        f"{metrics['precision']:.1%}"
    )
    print(
        f"재현율: "
        f"{metrics['recall']:.1%}"
    )

    print()
    print("처리 상태 요약")
    print(
        saved_results["summary"].to_string(
            index=False
        )
    )

    print()
    print("분개장 검증 완료")


# 이 파일을 직접 실행했을 때만 main 함수 실행
if __name__ == "__main__":
    main()