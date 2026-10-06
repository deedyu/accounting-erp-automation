"""기존 사용자 자료를 참조하지 않는 합성 Excel 예제 생성기."""
from pathlib import Path
import pandas as pd


def create_wide(path: Path, count: int) -> None:
    """제목행·복수 시트·세 개 차변·미매핑 열을 포함한 예제를 생성한다."""
    rows = []
    for index in range(count):
        rows.append({"작성자명": "합성 테스트", "전표 번호": f"TEST-{index:06}",
            "거래(일자)": f"2026-08-{index % 20 + 1:02}", "부서": "D001", "업체코드": "V001",
            "증빙유형": "영수증", "증빙번호": f"E-{index:06}", "적요": "합성 검증 거래", "거래유형": "테스트",
            "차변계정": "5130", "차변금액": "60원", "차변계정2": "1180", "차변금액2": 10,
            "차변 계정 코드 3": "1100", "차변금액3": 40, "대변계정": "1110", "대변금액": "110",
            "공급가액": 100, "부가세": 10, "합계금액": 110})
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        pd.DataFrame({"설명": ["실제 기업 자료가 아닌 테스트 파일"]}).to_excel(writer, sheet_name="안내", index=False)
        pd.DataFrame(rows).to_excel(writer, sheet_name="월별 분개", index=False, startrow=2)
        writer.sheets["월별 분개"].cell(1, 1, "8월 분개장 테스트")


def create_vertical(path: Path, vouchers: int) -> None:
    """같은 증빙번호를 전표 내 두 행에서 공유하는 세로형을 만든다."""
    rows = []
    for index in range(vouchers):
        for number, account, debit, credit in [(1, "1100", 100, 0), (2, "1110", 0, 100)]:
            rows.append({"journal_id": f"V-{index:06}", "date": f"2026-08-{index % 20 + 1:02}",
                "line_no": number, "account_code": account, "debit_amount": debit, "credit_amount": credit,
                "department_code": "D001", "vendor_code": "V001", "evidence_type": "영수증",
                "evidence_no": f"VE-{index:06}", "description": "합성 세로 분개", "추가 메모": "보존 대상"})
    pd.DataFrame(rows).to_excel(path, index=False, sheet_name="세로형")


if __name__ == "__main__":
    directory = Path(__file__).resolve().parent
    for name, count in [("wide_1000.xlsx", 1000), ("wide_5000.xlsx", 5000)]:
        path = directory / name
        if not path.exists():
            create_wide(path, count)
    path = directory / "vertical_1000_rows.xlsx"
    if not path.exists():
        create_vertical(path, 500)
