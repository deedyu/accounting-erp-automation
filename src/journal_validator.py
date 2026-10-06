"""회계 분개장의 입력 오류를 검증하고 처리 상태를 분류하는 프로그램."""

import pandas as pd
from pathlib import Path
from typing import Any
from decimal import Decimal, ROUND_HALF_UP, ROUND_HALF_EVEN, ROUND_DOWN
import json

if __name__ == "__main__" and not __package__:
    from _bootstrap import configure_script_imports
    configure_script_imports(__file__)

from src.journal_values import code, money, date_value, pair_columns


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
        .apply(code)
    )

    # 사용 중인 거래처 코드
    valid_partner_codes = set(
        vendors.loc[
            vendors["is_active"] == "Y",
            "partner_code"
        ]
        .dropna()
        .apply(code)
    )

    # 사용 중인 부서 코드
    valid_department_codes = set(
        departments.loc[
            departments["is_active"] == "Y",
            "department_code"
        ]
        .dropna()
        .apply(code)
    )

    return {
        "master_data": {"account": accounts, "partner": vendors, "department": departments},
        "valid_account_codes": valid_account_codes,
        "valid_partner_codes": valid_partner_codes,
        "valid_department_codes": valid_department_codes,
        "period_start": pd.Timestamp(period_start),
        "period_end": pd.Timestamp(period_end)
    }


ERROR_COLUMNS = ["voucher_id", "row_number", "column", "error_type", "severity", "detail", "_row_id"]


def load_validation_rules(path: str | Path | None = None) -> dict[str, Any]:
    """검증 정책을 읽고 심각도·세율·반올림 설정을 확인한다."""
    rules = json.loads(Path(path or PROJECT_ROOT / "config/validation_rules.json").read_text())
    if any(v not in {"ERROR", "WARNING", "INFO"} for v in rules.get("severity_overrides", {}).values()):
        raise ValueError("검증 심각도는 ERROR, WARNING, INFO만 허용합니다.")
    if rules.get("rounding") not in {"ROUND_HALF_UP", "ROUND_HALF_EVEN", "ROUND_DOWN"}:
        raise ValueError("지원하지 않는 세액 반올림 방식입니다.")
    return rules


def identified_journal(journal: pd.DataFrame) -> pd.DataFrame:
    """전표번호 누락에도 오류를 연결할 수 있도록 내부 행 식별자를 보완한다."""
    result = journal.copy()
    if "_row_id" not in result:
        result["_row_id"] = [f"r{i + 2}" for i in range(len(result))]
    if "row_number" not in result:
        result["row_number"] = list(range(2, len(result) + 2))
    return result


def validate_journal(journal: pd.DataFrame, standards: dict[str, Any]) -> pd.DataFrame:
    """원본 행과 연결하여 필수값·기준정보·금액·전표·증빙·기간을 검사한다."""
    rules = standards.get("rules") or load_validation_rules()
    frame = identified_journal(journal)
    detected = list(journal.attrs.get("normalization_errors", []))
    masters = {}
    for kind, master in standards.get("master_data", {}).items():
        key = f"{kind}_code"
        masters[kind] = {code(r[key]): str(r["is_active"]).strip().upper() == "Y" for _, r in master.iterrows()}
    fallback = {"account": "valid_account_codes", "partner": "valid_partner_codes", "department": "valid_department_codes"}
    for kind, field in fallback.items():
        if kind not in masters:
            masters[kind] = {code(v): True for v in standards[field]}
    voucher_keys = frame["voucher_id"].apply(code)
    duplicated_vouchers = voucher_keys.ne("") & voucher_keys.duplicated(keep=False)
    evidence_groups = frame.assign(_evidence=frame["evidence_no"].apply(code)).groupby("_evidence")["_row_id"].nunique()
    duplicated_evidence = set(evidence_groups[evidence_groups > 1].index) - {""}
    for index, row in frame.iterrows():
        def error(column: str, kind: str, detail: str, number: int | None = None) -> None:
            """원본 위치와 설정된 심각도로 오류를 추가한다."""
            detected.append({"voucher_id": row.get("voucher_id"), "row_number": int(number or row["row_number"]),
                             "column": column, "error_type": kind, "severity": rules.get("severity_overrides", {}).get(kind, "ERROR"),
                             "detail": detail, "_row_id": row["_row_id"]})
        for column in rules["required_fields"]:
            if is_missing(row.get(column)):
                error(column, "필수값 누락", f"{column}: 값이 없습니다.")
        if duplicated_vouchers.loc[index] and row.get("_layout", "wide") != "vertical":
            error("voucher_id", "중복 전표번호", "가로형 분개장에 같은 전표번호가 여러 번 있습니다.")
        for kind, label in [("department", "부서"), ("partner", "거래처")]:
            value = code(row.get(f"{kind}_code"))
            if value and value not in masters[kind]:
                error(f"{kind}_code", f"존재하지 않는 {label}", f"{value}: {label} 기준정보에 없습니다.")
            elif value and not masters[kind][value]:
                error(f"{kind}_code", f"비활성 {label}", f"{value}: 사용 중지된 {label}입니다.")
        totals = {}
        for side in ["debit", "credit"]:
            total, invalid = 0, False
            for account_col, amount_col in pair_columns(frame.columns, side):
                account = code(row.get(account_col))
                raw_amount = row.get(amount_col)
                number = row.get(f"_{side}_row_{account_col.rsplit('_', 1)[1]}", row["row_number"])
                number = int(row["row_number"] if pd.isna(number) else number)
                if account and account not in masters["account"]:
                    error(account_col, "존재하지 않는 계정과목", f"{account}: 계정 기준정보에 없습니다.", number)
                elif account and not masters["account"][account]:
                    error(account_col, "비활성 계정과목", f"{account}: 사용 중지된 계정입니다.", number)
                try:
                    amount = money(raw_amount)
                except ValueError as exc:
                    error(amount_col, "금액 형식 오류", f"{raw_amount}: {exc}", number)
                    invalid = True
                    continue
                if account and amount is None:
                    error(amount_col, "계정·금액 쌍 누락", "계정코드는 있지만 금액이 없습니다.", number)
                if not account and amount not in (None, 0):
                    error(account_col, "계정·금액 쌍 누락", "금액은 있지만 계정코드가 없습니다.", number)
                if amount is not None:
                    if amount < 0 and not rules["allow_negative"]:
                        error(amount_col, "허용되지 않은 금액", "음수 금액은 허용하지 않습니다.", number)
                    total += amount
            totals[side] = None if invalid else total
        amounts = {}
        for column in ["supply_amount", "vat_amount", "total_amount"]:
            try:
                amounts[column] = money(row.get(column))
                if amounts[column] is not None and amounts[column] < 0 and not rules["allow_negative"]:
                    error(column, "허용되지 않은 금액", "음수 금액은 허용하지 않습니다.")
            except ValueError as exc:
                amounts[column] = None
                error(column, "금액 형식 오류", f"{row.get(column)}: {exc}")
        debit, credit = totals["debit"], totals["credit"]
        if debit is not None and credit is not None:
            if debit != credit:
                error("debit_amount_1", "차변·대변 불일치", f"차변 {debit:,}원 / 대변 {credit:,}원")
            if debit == credit == 0 and not rules["allow_zero_voucher"]:
                error("debit_amount_1", "허용되지 않은 금액", "분개 금액이 모두 0원이거나 비어 있습니다.")
            if amounts["total_amount"] is not None and amounts["total_amount"] != debit:
                error("total_amount", "전표 합계 불일치", f"입력 {amounts['total_amount']:,}원 / 차변 {debit:,}원")
        supply, vat, total = (amounts[c] for c in ["supply_amount", "vat_amount", "total_amount"])
        if supply is not None and vat is not None and (supply > 0 or vat > 0):
            if total is not None and supply + vat != total:
                error("total_amount", "공급가액·부가세·총액 불일치", f"공급가액+부가세 {supply + vat:,}원 / 총액 {total:,}원")
            tax_type = code(row.get("tax_type"))
            rate = rules["tax_rates"].get(tax_type, rules["vat_rate"] if not tax_type else None)
            if rate is None:
                error("tax_type", "과세유형 확인", f"과세유형 '{tax_type}'의 세율을 설정해 주세요.")
            else:
                rounding = {"ROUND_HALF_UP": ROUND_HALF_UP, "ROUND_HALF_EVEN": ROUND_HALF_EVEN, "ROUND_DOWN": ROUND_DOWN}[rules["rounding"]]
                expected = int((Decimal(supply) * Decimal(rate)).quantize(Decimal("1"), rounding=rounding))
                if abs(vat - expected) > rules["vat_tolerance_won"]:
                    error("vat_amount", "부가세 계산 오류", f"입력 {vat:,}원 / 예상 {expected:,}원")
        if code(row.get("evidence_no")) in duplicated_evidence:
            error("evidence_no", "증빙번호 중복", "서로 다른 전표가 같은 증빙번호를 사용합니다.")
        date = date_value(row.get("transaction_date"))
        if not is_missing(row.get("transaction_date")) and pd.isna(date):
            error("transaction_date", "날짜 형식 오류", f"{row.get('transaction_date')}: 날짜로 변환할 수 없습니다.")
        elif not pd.isna(date) and not standards["period_start"] <= date < standards["period_end"]:
            error("transaction_date", "회계기간 이탈", f"{date.date()}: 선택한 회계기간 밖입니다.")
    return pd.DataFrame(detected, columns=ERROR_COLUMNS).sort_values(["row_number", "error_type"], kind="stable").reset_index(drop=True)


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


def classify_transactions(journal: pd.DataFrame, validation_result: pd.DataFrame) -> pd.DataFrame:
    """내부 행 식별자로 오류를 연결하고 세 상태와 기존 호환 상태를 만든다."""
    frame = identified_journal(journal)
    errors = validation_result.copy()
    if "severity" not in errors:
        errors["severity"] = "ERROR"
    key = "_row_id" if "_row_id" in errors else "voucher_id"
    groups = {k: group for k, group in errors.groupby(key, dropna=False)}
    counts, kinds, statuses = [], [], []
    for _, row in frame.iterrows():
        group = groups.get(row[key], errors.iloc[:0])
        severity = set(group["severity"])
        counts.append(len(group))
        kinds.append(", ".join(sorted(set(group["error_type"]))) or "없음")
        statuses.append("입력 불가" if "ERROR" in severity else "검토 필요" if "WARNING" in severity else "입력 가능")
    frame["error_count"], frame["error_types"], frame["processing_status"] = counts, kinds, statuses
    frame["legacy_processing_status"] = ["입력 가능" if s == "입력 가능" else "검토 필요" for s in statuses]
    frame["_sort_date"] = frame["transaction_date"].apply(date_value)
    frame["_sort_voucher"] = frame["voucher_id"].apply(code)
    return frame.sort_values(["_sort_date", "_sort_voucher", "row_number"], kind="stable", na_position="last").drop(columns=["_sort_date", "_sort_voucher"]).reset_index(drop=True)


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