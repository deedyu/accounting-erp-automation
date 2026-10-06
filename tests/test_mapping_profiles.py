"""매핑 수정·재사용 및 세로형 표준화 검사."""
from pathlib import Path
import pandas as pd
import pytest
from src.column_mapper import map_columns, mapping_profile, read_mapping_profile
from src.data_standardizer import standardize_excel_file


@pytest.mark.parametrize("columns", [["작성자명", "거래 일자", "전표번호"], ["전표번호", "거래 일자", "작성자명"], ["voucher_id", "transaction_date", "debit_amount"], ["전표_번호", "거래(일자)", "차변 금액"]])
def test_exact_alias_priority(columns: list[str]) -> None:
    """정확한 한글·영문 별칭을 순서·특수문자와 무관하게 확정한다."""
    result = map_columns(columns)
    assert set(result.loc[result.status == "자동 확정", "standard_column"]) >= {"voucher_id", "transaction_date"}


def test_manual_mapping_duplicate_and_profile() -> None:
    """수동 매핑을 적용하며 중복을 거부하고 JSON으로 재사용한다."""
    settings = {"날짜X": "transaction_date", "문서X": "voucher_id"}
    profile = read_mapping_profile(mapping_profile(settings, "테스트회사", "wide"))
    result = map_columns(list(settings), overrides=profile["mapping"])
    assert (result.status == "자동 확정").all()
    with pytest.raises(ValueError, match="여러 원본"):
        map_columns(["전표번호", "문서X"], overrides={"문서X": "voucher_id"})


def test_vertical_and_unmapped_values(tmp_path: Path) -> None:
    """같은 전표의 두 행을 보존하고 미매핑 값을 반환한다."""
    path = tmp_path / "vertical.xlsx"
    pd.DataFrame({"전표번호": ["V1", "V1"], "거래일자": ["2026-08-01"] * 2,
                  "계정코드": [1100, 1110], "차변금액": [100, 0], "대변금액": [0, 100], "작성자": ["가", "나"]}).to_excel(path, index=False)
    result = standardize_excel_file(path)
    assert result["layout"] == "vertical"
    assert len(result["dataframe"]) == 1
    assert result["dataframe"].iloc[0]["debit_amount_1"] == 100
    assert result["dataframe"].iloc[0]["credit_amount_1"] == 100
    assert result["unmapped_data"]["작성자"].tolist() == ["가", "나"]
