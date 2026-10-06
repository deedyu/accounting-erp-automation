"""기존 Python 파일 직접 실행을 지원하는 경로 설정."""

from pathlib import Path
import sys


def configure_script_imports(file_path: str) -> None:
    """직접 실행한 파일의 프로젝트 루트를 모듈 검색 경로에 추가한다."""
    project_root = str(Path(file_path).resolve().parents[1])
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
