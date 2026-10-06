"""코드·날짜·원 단위 금액의 공통 처리."""
from decimal import Decimal, InvalidOperation
from typing import Any
import re
import pandas as pd


def missing(value: Any) -> bool:
    """결측값과 공백 문자열을 확인한다."""
    return value is None or bool(pd.isna(value)) or str(value).strip() == ""


def code(value: Any) -> str:
    """문자 코드의 선행 0을 보존하고 Excel 정수 코드를 문자열로 바꾼다."""
    if missing(value):
        return ""
    if isinstance(value, (int, float)) and not isinstance(value, bool) and float(value).is_integer():
        return str(int(value))
    return str(value).strip()


def money(value: Any) -> int | None:
    """원 단위 정수로 변환하며 빈 값만 None으로 구분한다."""
    if missing(value):
        return None
    if isinstance(value, bool):
        raise ValueError("참/거짓은 금액으로 사용할 수 없습니다.")
    text = str(value).strip().replace(",", "").replace("₩", "").removesuffix("원").strip()
    if text.startswith("(") and text.endswith(")"):
        text = "-" + text[1:-1]
    try:
        amount = Decimal(text)
    except InvalidOperation as error:
        raise ValueError("숫자로 변환할 수 없는 금액입니다.") from error
    if not amount.is_finite() or amount != amount.to_integral_value():
        raise ValueError("유한한 정수 원 단위 금액만 허용합니다.")
    if abs(amount) > 9_007_199_254_740_991:
        raise ValueError("정확한 화면·Excel 표시를 지원하는 금액 범위를 초과했습니다.")
    return int(amount)


def date_value(value: Any) -> pd.Timestamp:
    """문자 날짜·Excel 일련번호를 날짜로 정규화한다."""
    if missing(value):
        return pd.NaT
    text = str(value).strip()
    if re.fullmatch(r"\d{8}", text):
        return pd.to_datetime(text, format="%Y%m%d", errors="coerce")
    if isinstance(value, (int, float)):
        if 1 <= value <= 100000:
            return pd.to_datetime(value, unit="D", origin="1899-12-30").normalize()
        return pd.NaT
    result = pd.to_datetime(value, errors="coerce", format="mixed")
    if pd.isna(result) or getattr(result, "tzinfo", None) is not None:
        return pd.NaT
    return result.normalize()


def pair_columns(columns: Any, side: str) -> list[tuple[str, str]]:
    """존재하는 모든 차변 또는 대변 계정·금액 열 쌍을 찾는다."""
    numbers = sorted({int(m.group(1)) for c in columns if (m := re.fullmatch(fr"{side}_(?:account|amount)_(\d+)", c))})
    return [(f"{side}_account_{n}", f"{side}_amount_{n}") for n in numbers]
