"""프로젝트 공통 경로와 실행 설정."""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIRECTORY = PROJECT_ROOT / "config"
MASTER_DIRECTORY = PROJECT_ROOT / "data" / "master"
UPLOAD_DIRECTORY = PROJECT_ROOT / "data" / "uploads"
RUN_DIRECTORY = PROJECT_ROOT / "data" / "processed" / "runs"
DATABASE_PATH = PROJECT_ROOT / "data" / "processed" / "accounting_history.db"
