"""원본 이름을 유지하는 업로드 파일 저장."""
from hashlib import sha256
from pathlib import Path
from src.settings import UPLOAD_DIRECTORY


def save_upload(content: bytes, filename: str, directory: Path = UPLOAD_DIRECTORY) -> tuple[Path, str]:
    """내용 해시별 폴더에 원본을 보존하고 경로와 해시를 반환한다."""
    name = Path(filename.replace("\\", "/")).name
    if not name or name in {".", ".."}:
        raise ValueError("올바른 업로드 파일명을 입력해 주세요.")
    digest = sha256(content).hexdigest()
    folder = directory / digest
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    if not path.exists():
        with path.open("xb") as target:
            target.write(content)
    return path, digest
