"""패키지와 기존 직접 실행 방식의 호환성을 확인한다."""

import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize("module", [
    "file_analyzer", "column_mapper", "data_standardizer", "journal_validator",
    "prepare_erp_upload", "daily_ledger", "adaptive_pipeline", "adaptive_erp_export",
    "adaptive_database", "load_database", "export_dashboard_data", "run_pipeline",
])
def test_package_import(project_root: Path, tmp_path: Path, module: str) -> None:
    """다른 작업 폴더에서도 루트 경로만으로 모듈을 불러온다."""
    env = {**os.environ, "PYTHONPATH": str(project_root), "PYTHONDONTWRITEBYTECODE": "1"}
    result = subprocess.run(
        [sys.executable, "-B", "-c", f"import src.{module}"],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("module", ["column_mapper", "data_standardizer", "adaptive_pipeline", "adaptive_erp_export"])
def test_existing_script_usage(project_root: Path, tmp_path: Path, module: str) -> None:
    """기존 파일 실행에서 import 오류 대신 한국어 사용법을 안내한다."""
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    env.pop("PYTHONPATH", None)
    result = subprocess.run(
        [sys.executable, "-B", str(project_root / "src" / f"{module}.py")],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 1
    assert "사용 방법" in result.stdout
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("entry", ["script", "module"])
def test_database_cli_help(project_root: Path, entry: str) -> None:
    """직접 실행과 모듈 실행에서 저장 경로 옵션을 제공한다."""
    command = [str(project_root / "src/adaptive_database.py")] if entry == "script" else ["-m", "src.adaptive_database"]
    result = subprocess.run(
        [sys.executable, "-B", *command, "--help"],
        cwd=project_root, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "--output-dir" in result.stdout
    assert "--database-path" in result.stdout


def test_legacy_direct_entrypoint(project_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """기존 직접 실행 진입점이 네 단계를 순서대로 연결한다."""
    import runpy
    from src import export_dashboard_data, journal_validator, load_database, prepare_erp_upload

    calls: list[str] = []

    def record(name: str) -> None:
        """실제 파일 갱신 대신 실행 순서를 기록한다."""
        calls.append(name)

    for module in [journal_validator, prepare_erp_upload, load_database, export_dashboard_data]:
        monkeypatch.setattr(module, "main", lambda name=module.__name__: record(name))
    monkeypatch.syspath_prepend(str(project_root / "src"))
    monkeypatch.setattr(sys, "argv", ["run_pipeline.py", "--legacy-demo"])
    runpy.run_path(str(project_root / "src/run_pipeline.py"), run_name="__main__")
    assert calls == ["src.journal_validator", "src.prepare_erp_upload", "src.load_database", "src.export_dashboard_data"]


def test_streamlit_startup(project_root: Path) -> None:
    """업로드 전 Streamlit 화면이 import 오류 없이 열린다."""
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file(str(project_root / "app.py")).run(timeout=20)
    assert not app.exception
    assert app.title[0].value == "회계 분개장 자동 분석 시스템"
    assert "업로드" in app.info[0].value
