"""회계 검증의 경계값과 상태 분류 검사."""
from copy import deepcopy
from typing import Any
import pandas as pd
import pytest
from src.journal_validator import build_validation_standards, validate_journal, classify_transactions, load_validation_rules


@pytest.fixture
def valid_row() -> dict[str, Any]:
    """외부 파일과 독립적인 정상 전표를 만든다."""
    return dict(voucher_id="A", transaction_date="2026-08-01", department_code="D001", partner_code="V001",
                evidence_type="영수증", evidence_no="E1", description="테스트", debit_account_1=1100, debit_amount_1=110,
                credit_account_1=1110, credit_amount_1=110, supply_amount=100, vat_amount=10, total_amount=110)


@pytest.fixture
def standards() -> dict[str, Any]:
    """실제 마스터 파일 변경에 영향받지 않는 최소 기준정보를 만든다."""
    accounts = pd.DataFrame({"account_code": [1100, 1110], "is_active": ["Y", "Y"]})
    vendors = pd.DataFrame({"partner_code": ["V001"], "is_active": ["Y"]})
    departments = pd.DataFrame({"department_code": ["D001"], "is_active": ["Y"]})
    return build_validation_standards(accounts, vendors, departments, "2026-08-01", "2026-09-01")


@pytest.mark.parametrize("field,value,kind", [
    ("voucher_id", None, "필수값 누락"), ("description", "", "필수값 누락"),
    ("department_code", "D999", "존재하지 않는 부서"), ("partner_code", "V999", "존재하지 않는 거래처"),
    ("debit_account_1", "1100.5", "존재하지 않는 계정과목"), ("debit_amount_1", "오류", "금액 형식 오류"),
    ("vat_amount", "오류", "금액 형식 오류"), ("total_amount", "오류", "금액 형식 오류"),
    ("debit_amount_1", -110, "허용되지 않은 금액"), ("debit_amount_1", 110.5, "금액 형식 오류"),
    ("debit_amount_1", 120, "차변·대변 불일치"), ("vat_amount", 11, "부가세 계산 오류"),
    ("total_amount", 120, "공급가액·부가세·총액 불일치"),
    ("transaction_date", "잘못된날짜", "날짜 형식 오류"), ("transaction_date", "2026-09-01", "회계기간 이탈"),
    ("debit_account_1", None, "계정·금액 쌍 누락"), ("debit_amount_1", None, "계정·금액 쌍 누락"),
    ("evidence_no", None, "필수값 누락"),
])
def test_errors_block_erp(valid_row: dict, standards: dict, field: str, value: Any, kind: str) -> None:
    """잘못된 값은 행 번호가 있는 오류가 되고 입력을 차단한다."""
    valid_row[field] = value
    frame = pd.DataFrame([valid_row])
    errors = validate_journal(frame, standards)
    assert kind in set(errors.error_type)
    assert errors.row_number.eq(2).all()
    assert classify_transactions(frame, errors).iloc[0].processing_status == "입력 불가"


@pytest.mark.parametrize("kind,key", [("account", "debit_account_1"), ("department", "department_code"), ("partner", "partner_code")])
def test_inactive_master(valid_row: dict, standards: dict, kind: str, key: str) -> None:
    """존재하지만 비활성인 코드를 별도로 구분한다."""
    standards = deepcopy(standards)
    master = standards["master_data"][kind]
    master.loc[master[f"{kind}_code"].astype(str) == str(valid_row[key]), "is_active"] = "N"
    errors = validate_journal(pd.DataFrame([valid_row]), standards)
    assert any(t.startswith("비활성") for t in errors.error_type)


def test_duplicates_and_missing_ids(valid_row: dict, standards: dict) -> None:
    """중복 전표·증빙과 여러 결측 전표를 서로 혼동하지 않는다."""
    frame = pd.DataFrame([valid_row, valid_row])
    errors = validate_journal(frame, standards)
    assert {"중복 전표번호", "증빙번호 중복"} <= set(errors.error_type)
    frame.loc[0, "voucher_id"] = None
    frame.loc[1, "evidence_no"] = "E2"
    errors = validate_journal(frame, standards)
    result = classify_transactions(frame, errors)
    assert result.processing_status.tolist() == ["입력 불가", "입력 가능"]


def test_warning_and_info(valid_row: dict, standards: dict) -> None:
    """경고와 참고 사항을 오류와 구분하여 상태를 결정한다."""
    valid_row["tax_type"] = "별도세율"
    frame = pd.DataFrame([valid_row])
    errors = validate_journal(frame, standards)
    assert classify_transactions(frame, errors).iloc[0].processing_status == "검토 필요"
    errors["severity"] = "INFO"
    assert classify_transactions(frame, errors).iloc[0].processing_status == "입력 가능"


def test_valid_journal_preserves_input(valid_row: dict, standards: dict) -> None:
    """정상 전표는 오류 없이 입력 가능하며 검증 전후 원본이 같다."""
    frame = pd.DataFrame([valid_row])
    original = frame.copy(deep=True)
    errors = validate_journal(frame, standards)
    assert errors.empty
    result = classify_transactions(frame, errors).iloc[0]
    assert result.processing_status == "입력 가능"
    assert result.error_count == 0
    assert result.error_types == "없음"
    pd.testing.assert_frame_equal(frame, original)


@pytest.mark.parametrize("value", [None, float("nan"), "", "   "])
def test_required_description_missing_values(valid_row: dict, standards: dict, value: Any) -> None:
    """결측 표현이 달라도 필수값 오류의 위치와 유형은 동일하다."""
    valid_row["description"] = value
    errors = validate_journal(pd.DataFrame([valid_row]), standards)
    assert errors[["column", "error_type", "severity", "row_number", "_row_id"]].to_dict("records") == [
        {"column": "description", "error_type": "필수값 누락", "severity": "ERROR", "row_number": 2, "_row_id": "r2"}
    ]


@pytest.mark.parametrize("date,expected", [
    ("2026-07-31", ["회계기간 이탈"]),
    ("2026-08-01", []),
    ("2026-08-31 23:59:59", []),
    ("2026-09-01", ["회계기간 이탈"]),
])
def test_accounting_period_boundaries(valid_row: dict, standards: dict, date: str, expected: list) -> None:
    """회계기간 시작일은 포함하고 종료일은 제외한다."""
    valid_row["transaction_date"] = date
    errors = validate_journal(pd.DataFrame([valid_row]), standards)
    assert errors.error_type.tolist() == expected


@pytest.mark.parametrize("amount,expected", [
    (-1, "허용되지 않은 금액"),
    (0, "허용되지 않은 금액"),
    (1, None),
    (9_007_199_254_740_991, None),
    (9_007_199_254_740_992, "금액 형식 오류"),
    (float("inf"), "금액 형식 오류"),
    (True, "금액 형식 오류"),
])
def test_voucher_amount_boundaries(valid_row: dict, standards: dict, amount: Any, expected: str | None) -> None:
    """균형 전표로 금액 자체의 0원·최소·최대·범위 초과를 검사한다."""
    valid_row.update(debit_amount_1=amount, credit_amount_1=amount,
                     supply_amount=amount, vat_amount=0, total_amount=amount, tax_type="면세")
    errors = validate_journal(pd.DataFrame([valid_row]), standards)
    assert set(errors.error_type) == ({expected} if expected else set())


@pytest.mark.parametrize("difference,expected", [(-2, True), (-1, False), (0, False), (1, False), (2, True)])
def test_vat_tolerance_boundaries(valid_row: dict, standards: dict, difference: int, expected: bool) -> None:
    """세액 허용오차 ±1원 이내와 초과를 양방향으로 검사한다."""
    standards["rules"] = load_validation_rules()
    standards["rules"]["vat_tolerance_won"] = 1
    valid_row.update(vat_amount=10 + difference, total_amount=110 + difference,
                     debit_amount_1=110 + difference, credit_amount_1=110 + difference)
    errors = validate_journal(pd.DataFrame([valid_row]), standards)
    assert errors.error_type.tolist() == (["부가세 계산 오류"] if expected else [])


@pytest.mark.parametrize("rounding,vat", [("ROUND_HALF_UP", 1), ("ROUND_HALF_EVEN", 0), ("ROUND_DOWN", 0)])
def test_vat_half_won_rounding(valid_row: dict, standards: dict, rounding: str, vat: int) -> None:
    """세액 0.5원의 반올림 경계를 정책별로 확인한다."""
    standards["rules"] = load_validation_rules()
    standards["rules"]["rounding"] = rounding
    valid_row.update(supply_amount=5, vat_amount=vat, total_amount=5 + vat,
                     debit_amount_1=5 + vat, credit_amount_1=5 + vat)
    assert validate_journal(pd.DataFrame([valid_row]), standards).empty


def test_empty_journal(valid_row: dict, standards: dict) -> None:
    """표준 열이 있는 빈 입력에도 오류 결과와 상태 열을 반환한다."""
    frame = pd.DataFrame([valid_row]).iloc[:0]
    errors = validate_journal(frame, standards)
    assert errors.empty
    assert errors.columns.tolist() == ["voucher_id", "row_number", "column", "error_type", "severity", "detail", "_row_id"]
    result = classify_transactions(frame, errors)
    assert result.empty
    assert {"error_count", "error_types", "processing_status"} <= set(result.columns)
