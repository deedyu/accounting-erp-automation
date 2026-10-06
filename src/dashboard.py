"""처리 결과의 Streamlit 표시와 다운로드."""
from pathlib import Path
from typing import Any
import json
import pandas as pd
import streamlit as st
from src.adaptive_database import list_runs, load_run
from src.settings import DATABASE_PATH, PROJECT_ROOT
from src.result_exporter import clean_value
from src.prepare_erp_upload import build_erp_json

LABELS = {"transaction_date": "거래일자", "voucher_id": "전표번호", "line_pair": "순번", "line_no": "순번",
          "transaction_type": "거래유형", "department_code": "부서", "partner_code": "거래처", "description": "적요",
          "debit_account_code": "차변계정코드", "debit_account_name": "차변계정과목", "credit_account_code": "대변계정코드",
          "credit_account_name": "대변계정과목", "debit_amount": "차변금액", "credit_amount": "대변금액",
          "difference": "전표차액", "balance_status": "차대변상태", "processing_status": "처리상태", "error_types": "오류유형",
          "transaction_count": "전표 수", "debit_total": "차변 합계", "credit_total": "대변 합계", "unparsed_amount_count": "금액 확인 건수"}


def show_table(frame: pd.DataFrame, key: str, *, page_size: int = 100) -> None:
    """숫자를 유지한 채 금액 서식을 적용하고 표를 페이지로 나눠 표시한다."""
    if frame.empty:
        st.info("표시할 데이터가 없습니다.")
        return
    frame = frame[[c for c in frame if not c.startswith("_")]].copy()
    pages = max(1, (len(frame) + page_size - 1) // page_size)
    page = st.number_input("페이지", 1, pages, 1, key=f"page_{key}") if pages > 1 else 1
    sample = frame.iloc[(page - 1) * page_size:page * page_size].copy()
    money_columns = [c for c in sample if ("amount" in c and not c.endswith("count")) or c in {"debit_total", "credit_total", "difference"}]
    for column in sample:
        if column in {"transaction_date", "period_start", "period_end", "processed_at"}:
            sample[column] = pd.to_datetime(sample[column], errors="coerce").dt.strftime("%Y-%m-%d")
    sample = sample.rename(columns=LABELS)
    money_names = [LABELS.get(c, c) for c in money_columns]
    # Styler의 표시만 변경하며 원래 계산용 데이터는 숫자로 유지한다.
    formats = {c: lambda v: f"{v:,.0f}원" if isinstance(v, (int, float)) and not pd.isna(v) else "—" if pd.isna(v) else str(v) for c in money_names}
    st.dataframe(sample.style.format(formats), use_container_width=True, hide_index=True,
                 column_config={c: st.column_config.NumberColumn(c + "(원)") for c in money_names if pd.api.types.is_numeric_dtype(sample[c])})
    st.caption(f"전체 {len(frame):,}행 · {page}/{pages}페이지")


def show_daily_ledger_dashboard(result: dict[str, Any], key: str = "current") -> None:
    """일별 조회와 정상·전체 합계를 구분하고 선택 범위 다운로드를 제공한다."""
    st.subheader("날짜별 차변·대변 대조")
    ledger = result["daily_ledger"].copy()
    if ledger.empty:
        st.info("분개장 데이터가 없습니다.")
        return
    ledger["transaction_date"] = pd.to_datetime(ledger.transaction_date, errors="coerce")
    dates = sorted(ledger.transaction_date.dropna().dt.strftime("%Y-%m-%d").unique())
    months = sorted({value[:7] for value in dates})
    month = st.selectbox("조회 월", ["전체 기간", *months], key=f"month_{key}")
    available_dates = dates if month == "전체 기간" else [d for d in dates if d.startswith(month)]
    selected = st.selectbox("조회 날짜", ["월 전체", *available_dates], key=f"date_{key}")
    scope = st.radio("집계 범위", ["전체 전표", "입력 가능 전표"], horizontal=True, key=f"scope_{key}")
    if scope == "입력 가능 전표":
        ledger = ledger.loc[ledger.processing_status.eq("입력 가능")]
    if month != "전체 기간":
        ledger = ledger.loc[ledger.transaction_date.dt.strftime("%Y-%m").eq(month)]
    if selected != "월 전체":
        ledger = ledger.loc[ledger.transaction_date.dt.strftime("%Y-%m-%d").eq(selected)]
    columns = ["transaction_date", "voucher_id", "line_pair", "transaction_type", "department_code", "partner_code", "description",
               "debit_account_code", "debit_account_name", "credit_account_code", "credit_account_name", "debit_amount", "credit_amount",
               "difference", "balance_status", "processing_status", "error_types"]
    display = ledger.reindex(columns=columns)
    show_table(display, f"ledger_{key}")
    daily = result["daily_summary" if scope == "전체 전표" else "ready_daily_summary"].copy()
    if not daily.empty:
        date_text = pd.to_datetime(daily.transaction_date).dt.strftime("%Y-%m-%d")
        if month != "전체 기간":
            daily = daily.loc[date_text.str.startswith(month)]
        if selected != "월 전체":
            daily = daily.loc[date_text.eq(selected)]
        show_table(daily, f"daily_{key}")
    debit = sum(pd.to_numeric(ledger.get("debit_amount", pd.Series(dtype=int)), errors="coerce").fillna(0))
    credit = sum(pd.to_numeric(ledger.get("credit_amount", pd.Series(dtype=int)), errors="coerce").fillna(0))
    total = pd.DataFrame([{"transaction_count": int(ledger.line_pair.eq(1).sum()),
                           "debit_total": debit, "credit_total": credit, "difference": debit - credit,
                           "balance_status": "확인 필요" if ledger[["debit_amount", "credit_amount"]].isna().any().any() else "일치" if debit == credit else "불일치"}])
    st.write("조회 범위 최종 합계 — " + scope)
    show_table(total, f"total_{key}")
    st.caption("전체 합계는 검토·입력 불가 전표도 포함합니다. 날짜 해석 불가 행은 일계표에서 제외되지만 전체 기간 최종 합계에는 포함됩니다. 금액 해석 불가 값은 합산할 수 없으므로 오류 목록과 함께 확인하세요.")
    erp = result["erp_upload"].copy()
    if not erp.empty:
        date_text = pd.to_datetime(erp.transaction_date).dt.strftime("%Y-%m-%d")
        if month != "전체 기간":
            erp = erp.loc[date_text.str.startswith(month)]
        if selected != "월 전체":
            erp = erp.loc[date_text.eq(selected)]
    st.download_button("선택 범위 ERP CSV 다운로드", erp.to_csv(index=False).encode("utf-8-sig"), "erp_selected.csv", key=f"selected_csv_{key}")
    records = build_erp_json(erp) if not erp.empty else []
    st.download_button("선택 범위 ERP JSON 다운로드", json.dumps(clean_value(records), ensure_ascii=False, indent=2).encode(), "erp_selected.json", key=f"selected_json_{key}")


def show_dashboard(result: dict[str, Any], key: str = "current") -> None:
    """상태별 KPI·차트·장부·ERP·전체 다운로드를 표시한다."""
    summary = result["summary"].iloc[0]
    st.subheader("처리 결과")
    cols = st.columns(4)
    for column, label, field in zip(cols, ["전체 전표", "입력 가능", "검토 필요", "입력 불가"], ["total_transactions", "ready_transactions", "warning_transactions", "blocked_transactions"]):
        column.metric(label, f"{int(summary.get(field, 0)):,}건")
    st.caption(f"실행 ID: {result['database_result']['run_id']} · ERP 업로드용 파일 생성 및 연동 준비")
    classified, errors = result["classified_journal"], result["validation_result"]
    if not classified.empty:
        left, right = st.columns(2)
        with left:
            st.write("처리 상태별 전표 수")
            st.bar_chart(classified.processing_status.value_counts())
        with right:
            st.write("오류 유형별 집계")
            if not errors.empty:
                st.bar_chart(errors.error_type.value_counts())
        for field, label in [("department_code", "부서"), ("partner_code", "거래처")]:
            with st.expander(label + "별 집계"):
                st.bar_chart(classified.groupby(field, dropna=False).size().rename("전표 수"))
        for status in ["입력 가능", "검토 필요", "입력 불가"]:
            with st.expander(status + " 전표"):
                show_table(classified.loc[classified.processing_status.eq(status)], f"{key}_{status}")
    daily = result["daily_summary"]
    if not daily.empty:
        st.write("날짜별 차변·대변 추이")
        chart = daily.copy()
        chart["transaction_date"] = pd.to_datetime(chart.transaction_date)
        st.line_chart(chart.set_index("transaction_date")[["debit_total", "credit_total"]].rename(columns=LABELS))
    with st.expander("상세 검증 오류"):
        show_table(errors, f"errors_{key}")
    show_daily_ledger_dashboard(result, key)
    st.subheader("ERP 변환 결과")
    show_table(result["erp_upload"], f"erp_{key}")
    st.subheader("전체 결과 다운로드")
    for name, path in result["output_paths"].items():
        path = Path(path)
        if path.is_file():
            st.download_button(path.name + " 다운로드", path.read_bytes(), path.name, key=f"download_{key}_{name}")
        else:
            st.warning(f"결과 파일을 찾을 수 없습니다: {path.name}")


def show_history() -> None:
    """새 실행 이력과 기존 DB의 요약 이력을 읽기 전용으로 조회한다."""
    st.subheader("이전 실행 이력")
    history = list_runs()
    if history.empty:
        st.info("저장된 실행 이력이 없습니다.")
    else:
        show_table(history.drop(columns=["summary_json"], errors="ignore"), "history")
        run_id = st.selectbox("조회할 실행", history.run_id.tolist(), key="history_run")
        if st.button("선택 실행 결과 조회"):
            st.session_state["history_result"] = load_run(run_id)
        if "history_result" in st.session_state:
            show_dashboard(st.session_state["history_result"], "history_result")
    legacy = PROJECT_ROOT / "data/processed/adaptive_accounting_erp.db"
    if legacy.exists():
        with st.expander("기존 버전 실행 이력(보존 자료)"):
            show_table(list_runs(legacy), "legacy_history")
