"""다양한 엑셀 구조의 원본 범위 보존 검사."""
from pathlib import Path
import pandas as pd
from src.file_analyzer import analyze_excel_file, read_sheet


def test_title_multiple_sheets_and_totals(tmp_path: Path) -> None:
    """제목·반복 헤더·합계행을 구분하고 원본 행 번호를 유지한다."""
    path = tmp_path / "structure.xlsx"
    rows = [["월별 분개장", None, None], ["전표번호", "거래일자", "차변금액"],
            ["A", "2026-08-01", 100], ["전표번호", "거래일자", "차변금액"], ["합계", None, 100]]
    with pd.ExcelWriter(path) as writer:
        pd.DataFrame().to_excel(writer, sheet_name="안내", index=False)
        pd.DataFrame(rows).to_excel(writer, sheet_name="분개", header=False, index=False)
    analysis = analyze_excel_file(path)
    assert analysis["sheet_count"] == 2
    assert analysis["sheets"]["분개"]["excel_header_row"] == 2
    data = read_sheet(path, "분개")
    assert len(data["dataframe"]) == 1
    assert data["row_numbers"] == [3]
    assert len(data["excluded_rows"]) == 2
    assert len(data["raw_dataframe"]) == 5
