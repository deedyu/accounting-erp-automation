from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]

SOURCE_FILE = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "bulk_journal.xlsx"
)

OUTPUT_FILE = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "journal_korean_headers.xlsx"
)


COLUMN_RENAME_MAP = {
    "voucher_id": "전표번호",
    "transaction_date": "거래 일자",
    "transaction_type": "거래유형",
    "department_code": "귀속부서",
    "partner_code": "업체코드",
    "evidence_type": "증빙구분",
    "evidence_no": "증빙번호",
    "description": "적요",
    "debit_account_1": "차변계정코드1",
    "debit_amount_1": "차변금액1",
    "debit_account_2": "차변계정코드2",
    "debit_amount_2": "차변금액2",
    "credit_account_1": "대변계정코드1",
    "credit_amount_1": "대변금액1",
    "credit_account_2": "대변계정코드2",
    "credit_amount_2": "대변금액2",
    "supply_amount": "공급가액",
    "vat_amount": "부가세액",
    "total_amount": "총금액",
    "remarks": "비고"
}


def create_korean_header_sample():
    """
    기존 데이터는 유지하고 열 이름만 다른 분개장 양식으로 변경한다.
    """
    dataframe = pd.read_excel(
        SOURCE_FILE,
        sheet_name="분개장"
    )

    dataframe = dataframe.rename(
        columns=COLUMN_RENAME_MAP
    )

    # 등록되지 않은 열도 구분하는지 확인하기 위한 테스트 항목이다.
    dataframe["작성자명"] = "테스트 담당자"

    dataframe.to_excel(
        OUTPUT_FILE,
        sheet_name="분개장",
        index=False
    )

    print(f"한글 열 테스트 파일 생성 완료: {OUTPUT_FILE}")
    print(f"행 수: {len(dataframe)}")
    print(f"열 수: {len(dataframe.columns)}")


if __name__ == "__main__":
    create_korean_header_sample()