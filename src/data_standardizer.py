from pathlib import Path
import sys
from typing import Any

import pandas as pd

# 기존 파일 직접 실행에서도 동일한 패키지 모듈을 사용한다.
if __name__ == "__main__" and not __package__:
    from _bootstrap import configure_script_imports

    configure_script_imports(__file__)

from src.column_mapper import load_column_aliases, map_columns, VERTICAL_COLUMNS
from src.file_analyzer import read_sheet, analyze_excel_file, normalize_header
from src.journal_values import missing, code, money


PROJECT_ROOT = Path(__file__).resolve().parents[1]
STANDARDIZED_DIRECTORY = PROJECT_ROOT / "data" / "standardized"


def vertical_to_wide(frame: pd.DataFrame) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """세로 분개를 전표별 임의 개수 계정 쌍으로 구성하고 행 출처를 유지한다."""
    frame = frame.copy()
    frame["_group"] = [code(v) or f"누락행:{n}" for v, n in zip(frame["voucher_id"], frame["row_number"])]
    rows, errors = [], []
    for _, group in frame.groupby("_group", sort=False):
        row = group.iloc[0].to_dict()
        row.pop("_group", None)
        row["_source_rows"] = group["row_number"].tolist()
        row["_layout"] = "vertical"
        def issue(number: int, column: str, kind: str, detail: str) -> None:
            """입력 행에 연결되는 표준화 오류를 기록한다."""
            errors.append({"_row_id": row["_row_id"], "voucher_id": row.get("voucher_id"), "row_number": number,
                           "column": column, "error_type": kind, "severity": "ERROR", "detail": detail})
        for field in ["transaction_date", "department_code", "partner_code", "evidence_no", "supply_amount", "vat_amount", "total_amount"]:
            if field in group:
                values = [v for v in group[field] if not missing(v)]
                if values:
                    row[field] = values[0]
                if len({str(v) for v in values}) > 1:
                    issue(int(row["row_number"]), field, "전표 공통정보 불일치", f"같은 전표의 {field} 값이 서로 다릅니다.")
        if "line_no" in group:
            nonempty = group.loc[~group["line_no"].apply(missing)]
            for _, item in nonempty.loc[nonempty["line_no"].duplicated(keep=False)].iterrows():
                issue(int(item["row_number"]), "line_no", "분개 순번 중복", "전표 내 순번이 중복됐습니다.")
        counts = {"debit": 0, "credit": 0}
        for _, item in group.iterrows():
            debit, credit = item.get("debit_amount"), item.get("credit_amount")
            if "amount" in group and "debit_credit_type" in group:
                side = str(item.get("debit_credit_type", "")).strip().lower()
                if side in {"차변", "debit", "dr", "d"}:
                    debit, credit = item["amount"], 0
                elif side in {"대변", "credit", "cr", "c"}:
                    debit, credit = 0, item["amount"]
                else:
                    issue(int(item["row_number"]), "debit_credit_type", "차대 구분 오류", "차변 또는 대변을 지정해 주세요.")
            active = []
            for side, value in [("debit", debit), ("credit", credit)]:
                try:
                    amount = money(value)
                    used = amount is not None and amount != 0
                except ValueError:
                    used = True
                if used:
                    active.append(side)
                    counts[side] += 1
                    n = counts[side]
                    row[f"{side}_account_{n}"] = item.get("account_code")
                    row[f"{side}_amount_{n}"] = value
                    row[f"_{side}_row_{n}"] = int(item["row_number"])
            if len(active) == 2:
                issue(int(item["row_number"]), "debit_amount", "양쪽 금액 입력", "세로형 한 행에는 차변 또는 대변 한쪽만 입력해야 합니다.")
            if not active:
                issue(int(item["row_number"]), "amount", "계정·금액 쌍 누락", "분개 행의 계정과 0이 아닌 금액을 확인해 주세요.")
        rows.append(row)
    return pd.DataFrame(rows), errors


def standardize_excel_file(
    file_path: str | Path, sheet_name: str | None = None, *, header_row: int | None = None,
    data_start: int | None = None, data_end: int | None = None,
    layout: str = "auto", mapping: dict[str, str | None] | None = None,
) -> dict[str, Any]:
    """선택 범위와 매핑을 적용하고 가로·세로 분개 및 미매핑 값을 보존한다."""
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"파일을 찾을 수 없습니다: {file_path}")
    if sheet_name is None:
        analysis = analyze_excel_file(file_path)
        sheet_name = max(analysis["sheets"], key=lambda name: analysis["sheets"][name]["column_count"] if analysis["sheets"][name]["row_count"] else -1)
    source = read_sheet(file_path, sheet_name, header_row=header_row, data_start=data_start, data_end=data_end)
    frame = source["dataframe"]
    if layout == "auto":
        layout = "vertical" if any(normalize_header(c) in {"accountcode", "계정코드", "계정과목코드"} for c in frame) else "wide"
    if layout not in {"wide", "vertical"}:
        raise ValueError("분개 형태는 wide 또는 vertical이어야 합니다.")
    mapped = map_columns(list(frame.columns), layout=layout, overrides=mapping)
    confirmed = {r.source_column: r.standard_column for r in mapped.itertuples() if r.status == "자동 확정"}
    unmapped = [c for c in frame if c not in confirmed]
    normalized = frame[list(confirmed)].rename(columns=confirmed).copy()
    required = ["voucher_id", "transaction_date", "department_code", "partner_code", "evidence_type", "evidence_no", "description"]
    required += ["account_code"] if layout == "vertical" else ["debit_account_1", "debit_amount_1", "credit_account_1", "credit_amount_1"]
    missing_columns = [c for c in required if c not in normalized]
    for column in required:
        if column not in normalized:
            normalized[column] = None
    normalized["row_number"] = source["row_numbers"]
    normalized["_row_id"] = [f"r{n}" for n in source["row_numbers"]]
    errors = []
    if layout == "vertical" and not normalized.empty:
        normalized, errors = vertical_to_wide(normalized)
    else:
        normalized["_layout"] = layout
    standard = [k for k in load_column_aliases() if k not in VERTICAL_COLUMNS and k != "tax_type"]
    for column in standard:
        if column not in normalized:
            normalized[column] = None
    normalized = normalized[standard + [c for c in normalized if c not in standard]]
    # 잘못된 값은 검증까지 보존하며 변환 실패를 0으로 바꾸지 않는다.
    for column in normalized:
        if "amount" in column and not column.startswith("_"):
            values = []
            for value in normalized[column]:
                try:
                    values.append(money(value))
                except ValueError:
                    values.append(value)
            normalized[column] = pd.Series(values, index=normalized.index, dtype=object)
    normalized.attrs["normalization_errors"] = errors
    return {"file_name": file_path.name, "sheet_name": sheet_name, "header_row": source["header_row"],
            "data_start": source["data_start"], "data_end": source["data_end"], "layout": layout,
            "dataframe": normalized, "mapping_result": mapped, "missing_columns": missing_columns,
            "unmapped_columns": unmapped, "unmapped_data": frame[unmapped].assign(row_number=source["row_numbers"]),
            "raw_dataframe": source["raw_dataframe"], "source_dataframe": frame,
            "excluded_rows": source["excluded_rows"], "normalization_errors": errors}


def save_standardized_file(result):
    """
    표준화된 분개장을 원본과 분리된 폴더에 엑셀로 저장한다.
    """
    STANDARDIZED_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True
    )

    original_stem = Path(result["file_name"]).stem
    output_path = (
        STANDARDIZED_DIRECTORY
        / f"standardized_{original_stem}.xlsx"
    )

    result["dataframe"].to_excel(
        output_path,
        sheet_name="표준분개장",
        index=False
    )

    return output_path


def print_standardization_result(result, output_path):
    """
    표준화 처리 결과를 터미널에 출력한다.
    """
    dataframe = result["dataframe"]

    print(f"\n원본 파일: {result['file_name']}")
    print(f"분석 시트: {result['sheet_name']}")
    print(f"데이터 행 수: {len(dataframe)}")
    print(f"표준 열 수: {len(dataframe.columns)}")
    print(f"누락된 표준 열: {result['missing_columns']}")
    print(f"매핑되지 않은 원본 열: {result['unmapped_columns']}")
    print(f"표준화 파일 저장 위치: {output_path}")

    print("\n표준 열 목록")
    print(dataframe.columns.tolist())

    print("\n앞부분 데이터")
    print(dataframe.head().to_string(index=False))


def main(file_path):
    result = standardize_excel_file(file_path)
    output_path = save_standardized_file(result)
    print_standardization_result(result, output_path)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(
            "사용 방법: "
            "python src/data_standardizer.py 변환할_엑셀파일.xlsx"
        )
        sys.exit(1)

    main(sys.argv[1])