"""엑셀 업로드·분석 설정·매핑 편집·결과 조회 화면."""
from pathlib import Path
from typing import Any
import json
import logging
from hashlib import sha256
import pandas as pd
import streamlit as st

from src.adaptive_database import run_and_save
from src.adaptive_pipeline import infer_accounting_period
from src.column_mapper import aliases_for_layout, mapping_profile, read_mapping_profile
from src.dashboard import show_dashboard, show_history, show_table
from src.data_standardizer import standardize_excel_file
from src.file_analyzer import analyze_excel_file
from src.file_storage import save_upload

st.set_page_config(page_title="회계 분개장 자동화", page_icon="📊", layout="wide")


@st.cache_data(show_spinner=False)
def analyze_upload(path: str, digest: str) -> dict[str, Any]:
    """내용 해시별 파일 분석 결과를 재사용한다."""
    return analyze_excel_file(path)


@st.cache_data(show_spinner=False)
def preview_upload(path: str, digest: str, options: dict[str, Any]) -> dict[str, Any]:
    """선택한 시트·범위·형식의 표준화 미리보기를 재사용한다."""
    return standardize_excel_file(path, **options)


def save_uploaded_file(uploaded_file: Any) -> tuple[Path, str]:
    """원본 이름을 유지하며 업로드 자료를 보존한다."""
    return save_upload(uploaded_file.getvalue(), uploaded_file.name)


def show_file_analysis(file_path: Path, digest: str) -> dict[str, Any]:
    """시트 분석과 파일 정보를 표시한다."""
    analysis = analyze_upload(str(file_path), digest)
    st.subheader("1. 파일 구조 분석")
    st.write({"원본 파일명": analysis["file_name"], "시트 수": analysis["sheet_count"]})
    with st.expander("전체 시트 구조"):
        st.dataframe(pd.DataFrame([{k: v for k, v in sheet.items() if k in {"sheet_name", "excel_header_row", "data_start", "data_end", "row_count", "column_count", "layout"}} for sheet in analysis["sheets"].values()]), hide_index=True)
    return analysis


def upload_screen() -> None:
    """업로드부터 매핑 확인과 분석 실행까지 연결한다."""
    uploaded = st.file_uploader("분개장 엑셀 파일을 선택하세요.", type=["xlsx", "xlsm"])
    if uploaded is None:
        st.info("분석할 엑셀 파일을 업로드해 주세요.")
        return
    path, digest = save_uploaded_file(uploaded)
    analysis = show_file_analysis(path, digest)
    names = analysis["sheet_names"]
    best = max(names, key=lambda n: analysis["sheets"][n]["column_count"] if analysis["sheets"][n]["row_count"] else -1)
    sheet = st.selectbox("2. 시트 선택", names, index=names.index(best), key=f"sheet_{digest}")
    detected = analysis["sheets"][sheet]
    prefix = f"{digest}_{sheet}"
    header = st.number_input("헤더 행(Excel 행 번호)", min_value=1, value=detected["excel_header_row"], key=f"header_{prefix}")
    start = st.number_input("첫 데이터 행", min_value=header + 1, value=max(header + 1, detected["data_start"]), key=f"start_{prefix}_{header}")
    end = st.number_input("마지막 데이터 행(포함)", min_value=start - 1, value=max(start - 1, detected["data_end"]), key=f"end_{prefix}_{header}")
    layout = st.selectbox("분개 구조", ["wide", "vertical"], index=int(detected["layout"] == "vertical"), format_func=lambda v: "가로형" if v == "wide" else "세로형", key=f"layout_{prefix}")
    options = dict(sheet_name=sheet, header_row=header - 1, data_start=start, data_end=end, layout=layout)
    preview = preview_upload(str(path), digest, options)
    st.subheader("3. 열 매핑 확인·수정")
    show_table(preview["source_dataframe"].head(20), "source_preview")
    profile_file = st.file_uploader("회사별 매핑 JSON 불러오기", type=["json"])
    profile = read_mapping_profile(profile_file.getvalue()) if profile_file else None
    mapping_frame = preview["mapping_result"].copy()
    mapping_frame["적용할 표준 열"] = [r.standard_column if r.status == "자동 확정" else "미매핑" for r in mapping_frame.itertuples()]
    if profile:
        if profile["layout"] != layout:
            st.error("매핑 설정의 분개 구조가 현재 선택과 다릅니다.")
            return
        mapping_frame["적용할 표준 열"] = [profile["mapping"].get(c) or "미매핑" for c in mapping_frame.source_column]
    targets = ["미매핑", *aliases_for_layout(list(preview["source_dataframe"].columns), layout)]
    edited = st.data_editor(mapping_frame, hide_index=True, use_container_width=True,
        disabled=["source_column", "standard_column", "matched_alias", "confidence", "status"],
        column_config={"적용할 표준 열": st.column_config.SelectboxColumn("적용할 표준 열", options=targets, required=True)},
        key=f"mapping_{prefix}_{header}_{start}_{end}_{layout}_{sha256(profile_file.getvalue()).hexdigest() if profile_file else 'auto'}")
    mapping = {r["source_column"]: None if r["적용할 표준 열"] == "미매핑" else r["적용할 표준 열"] for r in edited.to_dict("records")}
    chosen = [v for v in mapping.values() if v]
    if len(chosen) != len(set(chosen)):
        st.error("같은 표준 열에 여러 원본 열이 연결됐습니다. 중복 연결을 수정해 주세요.")
        return
    company = st.text_input("매핑 설정 이름", value="회사별 매핑")
    st.download_button("매핑 설정 JSON 다운로드", mapping_profile(mapping, company, layout), "column_mapping_profile.json", mime="application/json")
    if preview["missing_columns"]:
        st.caption("자동 매핑에서 부족한 필수 열: " + ", ".join(preview["missing_columns"]) + " · 수정 내용을 실행에 적용합니다.")
    with st.expander("미매핑 값·분리한 반복 헤더와 합계행"):
        st.dataframe(preview["unmapped_data"].head(100), hide_index=True)
        st.dataframe(preview["excluded_rows"].head(100), hide_index=True)
    start_period, end_period = infer_accounting_period(preview["dataframe"])
    st.subheader("4. 회계기간 확인")
    period_start = st.date_input("시작일", start_period.date(), key=f"period_start_{prefix}")
    period_end = st.date_input("종료일(미포함)", end_period.date(), key=f"period_end_{prefix}")
    signature = json.dumps([digest, options, mapping, str(period_start), str(period_end)], ensure_ascii=False, sort_keys=True)
    if st.session_state.get("execution_signature") != signature:
        st.session_state.pop("pipeline_result", None)
        st.session_state["execution_signature"] = signature
    if st.button("자동 검증 및 ERP 변환 실행", type="primary"):
        with st.spinner("분개장을 검증하고 결과 파일을 생성하고 있습니다."):
            result = run_and_save(path, **options, mapping=mapping, period_start=str(period_start), period_end=str(period_end))
            st.session_state["pipeline_result"] = result
        st.success("ERP 업로드용 파일 생성 및 연동 준비가 완료됐습니다.")
    if "pipeline_result" in st.session_state:
        show_dashboard(st.session_state["pipeline_result"])


st.title("회계 분개장 자동 분석 시스템")
st.write("월별 Excel 분개장을 분석하고 회계 검증, 일계표, ERP 업로드용 파일을 생성합니다.")
try:
    page = st.radio("작업 선택", ["분개장 분석", "이전 실행 이력"], horizontal=True)
    if page == "분개장 분석":
        upload_screen()
    else:
        show_history()
except (ValueError, FileNotFoundError, FileExistsError, RuntimeError) as error:
    st.error(str(error))
except Exception as error:
    logging.exception("분개장 처리 오류")
    st.error("파일 처리 중 예상하지 못한 오류가 발생했습니다. 파일 형식과 시트·범위 설정을 확인해 주세요.")
    with st.expander("오류 상세"):
        st.exception(error)
