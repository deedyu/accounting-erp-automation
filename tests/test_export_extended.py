"""가로·세로 분개와 빈 결과의 실제 출력 검사."""
from pathlib import Path
import json
import pandas as pd
from openpyxl import load_workbook
from src.adaptive_erp_export import run_full_pipeline


def test_no_ready_and_empty(tmp_path: Path) -> None:
    """정상 전표가 없거나 파일이 비어도 오류·다운로드 결과를 생성한다."""
    for name, data in [("empty", pd.DataFrame()), ("invalid", pd.DataFrame({"전표번호": [None], "거래일자": ["오류"], "적요": ["잘못된 전표"]}))]:
        source = tmp_path / f"{name}.xlsx"
        data.to_excel(source, index=False)
        result = run_full_pipeline(source, output_directory=tmp_path / name)
        assert result["erp_upload"].empty
        assert json.loads(result["output_paths"]["erp_json"].read_text()) == []
        assert result["output_paths"]["errors_excel"].exists()
        workbook = load_workbook(result["output_paths"]["erp_excel"])
        assert workbook.active.freeze_panes == "A2"
        assert workbook.active.auto_filter.ref
        workbook.close()


def test_vertical_output_and_excel_format(tmp_path: Path) -> None:
    """세로형의 전표별 균형·정렬·서식 및 정상 출력 대상을 확인한다."""
    source = tmp_path / "vertical.xlsx"
    pd.DataFrame({"전표번호": ["A"] * 3, "거래일자": ["2026-08-01"] * 3,
        "계정코드": [1100, 1110, 2110], "차변금액": [60, 40, 0], "대변금액": [0, 0, 100],
        "부서": ["D001"] * 3, "업체코드": ["V001"] * 3, "증빙유형": ["영수증"] * 3,
        "증빙번호": ["E1"] * 3, "적요": ["테스트"] * 3}).to_excel(source, index=False)
    result = run_full_pipeline(source, output_directory=tmp_path / "results")
    assert len(result["erp_upload"]) == 3
    assert result["validation_result"].empty
    assert result["erp_upload"].debit_amount.sum() == result["erp_upload"].credit_amount.sum() == 100
    workbook = load_workbook(result["output_paths"]["erp_excel"])
    sheet = workbook.active
    columns = [c.value for c in sheet[1]]
    assert columns.index("credit_amount") == columns.index("debit_amount") + 1
    assert sheet.cell(2, columns.index("amount") + 1).number_format == '#,##0"원";[Red]-#,##0"원"'
    assert sheet.cell(sheet.max_row, 1).value == "합계"
    workbook.close()
