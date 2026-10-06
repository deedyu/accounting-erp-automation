"""실제 결과 데이터로 Streamlit 렌더링을 확인한다."""
from pathlib import Path
import pandas as pd
from streamlit.testing.v1 import AppTest
from src.adaptive_database import run_and_save, load_run


def test_dashboard_invalid_and_history(tmp_path: Path) -> None:
    """정상 0건과 이전 실행 조회도 화면 오류 없이 표시한다."""
    source = tmp_path / "invalid.xlsx"
    pd.DataFrame({"전표번호": [None], "거래일자": ["잘못된날짜"], "적요": ["오류자료"]}).to_excel(source, index=False)
    database = tmp_path / "history.db"
    result = run_and_save(source, output_directory=tmp_path / "out", database_path=database)
    for item in [result, load_run(result["database_result"]["run_id"], database)]:
        app = AppTest.from_string('import streamlit as st\nfrom src.dashboard import show_dashboard\nshow_dashboard(st.session_state["result"])')
        app.session_state["result"] = item
        app.run(timeout=30)
        assert not app.exception
        assert [metric.value for metric in app.metric] == ["1건", "0건", "0건", "1건"]
