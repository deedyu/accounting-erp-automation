from pathlib import Path
import sys
import json
import re
from typing import Any

import pandas as pd


def normalize_header(value: Any) -> str:
    """헤더 비교용으로 문자와 숫자만 남긴다."""
    return re.sub(r"[^\w가-힣]", "", str(value).lower()).replace("_", "")


def header_aliases() -> set[str]:
    """설정 사전의 모든 헤더 별칭을 반환한다."""
    path = Path(__file__).resolve().parents[1] / "config/column_aliases.json"
    aliases = json.loads(path.read_text())
    return {normalize_header(v) for k, values in aliases.items() for v in [k, *values]}


def detect_header_row(file_path: str | Path, sheet_name: str | int, preview_rows: int = 100) -> int:
    """별칭 일치와 문자 비율로 헤더 행을 추정한다(0부터 시작)."""
    preview = pd.read_excel(file_path, sheet_name=sheet_name, header=None, nrows=preview_rows)
    aliases = header_aliases()
    scores = []
    for index, row in preview.iterrows():
        values = row.dropna().tolist()
        if values:
            hits = len({normalize_header(v) for v in values} & aliases)
            score = hits * 100 + sum(isinstance(v, str) for v in values) / len(values)
            scores.append((score, -index))
    return int(-max(scores)[1]) if scores else 0


def read_sheet(
    file_path: str | Path, sheet_name: str | int, *, header_row: int | None = None,
    data_start: int | None = None, data_end: int | None = None,
) -> dict[str, Any]:
    """범위를 읽고 반복 헤더·합계행을 원본과 분리해 보존한다."""
    raw = pd.read_excel(file_path, sheet_name=sheet_name, header=None, dtype=object, keep_default_na=False).replace(r"^\s*$", pd.NA, regex=True)
    header = detect_header_row(file_path, sheet_name) if header_row is None else header_row
    if raw.empty:
        return {"dataframe": pd.DataFrame(), "raw_dataframe": raw, "excluded_rows": raw,
                "header_row": header, "data_start": 0, "data_end": 0, "row_numbers": []}
    if not 0 <= header < len(raw):
        raise ValueError("헤더 행이 시트 범위를 벗어났습니다.")
    names, counts = [], {}
    for number, value in enumerate(raw.iloc[header]):
        name = str(value).strip() if not pd.isna(value) else f"이름없는열_{number + 1}"
        counts[name] = counts.get(name, 0) + 1
        names.append(name if counts[name] == 1 else f"{name} [{counts[name]}]")
    start = header + 2 if data_start is None else data_start
    end = len(raw) if data_end is None else data_end
    if start < header + 2 or end > len(raw) or end < start - 1:
        raise ValueError("데이터 범위는 헤더 다음 행부터 시트 마지막 행 사이여야 합니다.")
    frame = raw.iloc[start - 1:end].copy()
    frame.columns = names
    excluded = []
    keep = []
    for index, row in frame.iterrows():
        values = row.dropna()
        repeated = sum(normalize_header(v) == normalize_header(names[i]) for i, v in enumerate(row) if not pd.isna(v)) >= max(2, len(values) * .8)
        total = not values.empty and str(values.iloc[0]).strip() in {"합계", "소계", "총계", "월계", "Total", "TOTAL"}
        if values.empty or repeated or total:
            excluded.append(index)
        else:
            keep.append(index)
    data = frame.loc[keep].infer_objects().reset_index(drop=True)
    omitted = frame.loc[excluded].copy()
    omitted.insert(0, "Excel 행 번호", [i + 1 for i in excluded])
    return {"dataframe": data, "raw_dataframe": raw, "excluded_rows": omitted,
            "header_row": header, "data_start": start, "data_end": end,
            "row_numbers": [i + 1 for i in keep]}


def infer_column_role(series):
    """
    열의 실제 값을 확인하여 날짜, 숫자, 문자 중 어떤 성격인지 추정한다.
    """
    non_null = series.dropna()

    if non_null.empty:
        return "empty"

    if pd.api.types.is_datetime64_any_dtype(non_null):
        return "datetime"

    if pd.api.types.is_numeric_dtype(non_null):
        return "numeric"

    text_values = non_null.astype(str).str.strip()

    # 쉼표가 포함된 금액도 숫자로 판단할 수 있도록 제거한다.
    numeric_values = pd.to_numeric(
        text_values.str.replace(",", "", regex=False),
        errors="coerce"
    )
    numeric_ratio = numeric_values.notna().mean()

    if numeric_ratio >= 0.8:
        return "numeric_candidate"

    # 날짜처럼 생긴 값이 충분히 있을 때만 날짜 변환을 시도한다.
    date_pattern = r"^\d{4}[-/.]\d{1,2}[-/.]\d{1,2}(?:\s.*)?$"
    date_pattern_ratio = text_values.str.match(
        date_pattern,
        na=False
    ).mean()

    if date_pattern_ratio >= 0.8:
        date_values = pd.to_datetime(
            text_values,
            errors="coerce"
        )
        date_ratio = date_values.notna().mean()

        if date_ratio >= 0.8:
            return "datetime_candidate"

    return "text"


def analyze_sheet(file_path: str | Path, sheet_name: str) -> dict[str, Any]:
    """시트별 헤더·데이터 범위·자료형과 구조 후보를 분석한다."""
    result = read_sheet(file_path, sheet_name)
    frame = result["dataframe"]
    columns = []
    for name in frame:
        series = frame[name]
        columns.append({"column_name": name, "pandas_dtype": str(series.dtype),
                        "inferred_role": infer_column_role(series), "non_null_count": int(series.notna().sum()),
                        "missing_count": int(series.isna().sum()), "missing_rate": round(float(series.isna().mean() * 100), 2),
                        "unique_count": int(series.nunique())})
    vertical = any(normalize_header(c) in {"accountcode", "계정코드", "계정과목코드"} for c in frame)
    return {"sheet_name": sheet_name, "header_row": result["header_row"],
            "excel_header_row": result["header_row"] + 1, "data_start": result["data_start"],
            "data_end": result["data_end"], "layout": "vertical" if vertical else "wide",
            "row_count": len(frame), "column_count": len(frame.columns),
            "duplicate_row_count": int(frame.duplicated().sum()), "columns": list(frame.columns),
            "column_analysis": pd.DataFrame(columns), "sample": frame.head(5),
            "excluded_rows": result["excluded_rows"]}


def analyze_excel_file(file_path):
    """
    엑셀 파일에 포함된 모든 시트를 찾아 각각 자동 분석한다.
    """
    file_path = Path(file_path)

    if not file_path.exists():
        raise FileNotFoundError(f"파일을 찾을 수 없습니다: {file_path}")

    if file_path.suffix.lower() not in {".xlsx", ".xlsm"}:
        raise ValueError("현재는 .xlsx 또는 .xlsm 파일만 분석할 수 있습니다.")

    excel_file = pd.ExcelFile(file_path)

    result = {
        "file_name": file_path.name,
        "file_path": str(file_path.resolve()),
        "sheet_count": len(excel_file.sheet_names),
        "sheet_names": excel_file.sheet_names,
        "sheets": {}
    }

    for sheet_name in excel_file.sheet_names:
        result["sheets"][sheet_name] = analyze_sheet(
            file_path,
            sheet_name
        )

    return result


def print_analysis(result):
    """
    터미널에서 확인할 수 있도록 분석 결과를 출력한다.
    """
    print(f"\n파일명: {result['file_name']}")
    print(f"시트 수: {result['sheet_count']}")
    print(f"시트 목록: {result['sheet_names']}")

    for sheet_name, sheet_result in result["sheets"].items():
        print(f"\n[시트: {sheet_name}]")
        print(f"감지된 헤더 행: {sheet_result['excel_header_row']}행")
        print(f"데이터 행 수: {sheet_result['row_count']}")
        print(f"열 수: {sheet_result['column_count']}")
        print(f"완전 중복 행 수: {sheet_result['duplicate_row_count']}")
        print(f"열 목록: {sheet_result['columns']}")

        print("\n열별 분석")
        print(sheet_result["column_analysis"].to_string(index=False))

        print("\n앞부분 데이터")
        print(sheet_result["sample"].to_string(index=False))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(
            "사용 방법: "
            "python src/file_analyzer.py 분석할_엑셀파일.xlsx"
        )
        sys.exit(1)

    analysis_result = analyze_excel_file(sys.argv[1])
    print_analysis(analysis_result)