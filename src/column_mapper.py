from difflib import SequenceMatcher
from pathlib import Path
import json
import re
import sys
from typing import Any

import pandas as pd

# 기존 파일 직접 실행에서도 동일한 패키지 모듈을 사용한다.
if __name__ == "__main__" and not __package__:
    from _bootstrap import configure_script_imports

    configure_script_imports(__file__)

from src.file_analyzer import analyze_excel_file


# 현재 프로젝트 폴더를 기준으로 열 이름 사전의 위치를 설정한다.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ALIAS_PATH = PROJECT_ROOT / "config" / "column_aliases.json"


def normalize_column_name(column_name):
    """
    열 이름 비교를 위해 공백, 특수문자와 대소문자 차이를 제거한다.
    예: '거래 일자'와 '거래_일자'를 같은 형태로 비교할 수 있다.
    """
    normalized = str(column_name).strip().lower()
    normalized = re.sub(r"[^\w가-힣]", "", normalized).replace("_", "")

    return normalized


def load_column_aliases(alias_path=DEFAULT_ALIAS_PATH):
    """
    표준 열 이름과 사용 가능한 유사 표현을 JSON 파일에서 불러온다.
    """
    alias_path = Path(alias_path)

    if not alias_path.exists():
        raise FileNotFoundError(
            f"열 이름 사전을 찾을 수 없습니다: {alias_path}"
        )

    with open(alias_path, "r", encoding="utf-8") as file:
        return json.load(file)


def calculate_similarity(source_column, alias):
    """
    업로드된 열 이름과 사전에 등록된 표현의 유사도를 계산한다.
    """
    source_normalized = normalize_column_name(source_column)
    alias_normalized = normalize_column_name(alias)

    if source_normalized == alias_normalized:
        return 1.0

    return SequenceMatcher(
        None,
        source_normalized,
        alias_normalized
    ).ratio()


def find_best_match(source_column, aliases, used_targets):
    """
    한 개의 업로드 열과 가장 유사한 표준 열을 찾는다.
    이미 다른 열에 연결된 표준 열은 중복 매핑하지 않는다.
    """
    best_target = None
    best_alias = None
    best_score = 0.0

    for standard_column, alias_list in aliases.items():
        if standard_column in used_targets:
            continue

        candidates = [standard_column] + alias_list

        for alias in candidates:
            score = calculate_similarity(source_column, alias)

            if score > best_score:
                best_target = standard_column
                best_alias = alias
                best_score = score

    return best_target, best_alias, best_score


VERTICAL_COLUMNS = {"line_no", "account_code", "account_name", "debit_amount", "credit_amount", "debit_credit_type", "amount"}


def aliases_for_layout(source_columns: list[str], layout: str = "wide", alias_path: Path = DEFAULT_ALIAS_PATH) -> dict[str, list[str]]:
    """분개 형태에 맞는 별칭과 여러 계정 쌍의 별칭을 구성한다."""
    aliases = load_column_aliases(alias_path)
    if layout == "wide":
        aliases = {k: v for k, v in aliases.items() if k not in VERTICAL_COLUMNS}
        for source in source_columns:
            normalized = normalize_column_name(source)
            match = re.fullmatch(r"(차변|대변)(계정코드|계정|금액|액)(\d+)", normalized)
            english = re.fullmatch(r"(debit|credit)(account|amount)(\d+)", normalized)
            if match:
                side, field, number = match.groups()
                key = f"{'debit' if side == '차변' else 'credit'}_{'account' if '계정' in field else 'amount'}_{number}"
                aliases.setdefault(key, []).append(source)
            elif english:
                side, field, number = english.groups()
                aliases.setdefault(f"{side}_{field}_{number}", []).append(source)
    else:
        aliases = {k: v for k, v in aliases.items() if not re.match(r"(debit|credit)_(account|amount)_", k)}
    return aliases


def map_columns(source_columns: list[str], alias_path: Path = DEFAULT_ALIAS_PATH, *, layout: str = "wide", overrides: dict[str, str | None] | None = None) -> pd.DataFrame:
    """정확 일치를 먼저 확정하고 불확실한 후보는 사용자 확인으로 남긴다."""
    sources = list(source_columns)
    aliases = aliases_for_layout(sources, layout, alias_path)
    selected: dict[str, str] = {}
    rows: dict[str, dict[str, Any]] = {}
    # 모든 정확 일치를 먼저 수집하여 원본 열 순서의 영향을 없앤다.
    claims: dict[str, list[tuple[str, str]]] = {}
    for source in sources:
        for target, names in aliases.items():
            exact = next((name for name in [target, *names] if normalize_column_name(source) == normalize_column_name(name)), None)
            if exact is not None:
                claims.setdefault(target, []).append((source, exact))
    for target, matches in claims.items():
        for source, alias in matches:
            status = "자동 확정" if len(matches) == 1 else "확인 필요"
            rows[source] = {"source_column": source, "standard_column": target, "matched_alias": alias,
                            "confidence": 100.0, "status": status}
            if status == "자동 확정":
                selected[source] = target
    for source in sources:
        if source in rows:
            continue
        target, alias, score = find_best_match(source, aliases, set(selected.values()))
        rows[source] = {"source_column": source, "standard_column": target if score >= .65 else None,
                        "matched_alias": alias if score >= .65 else None, "confidence": round(score * 100, 1),
                        "status": "확인 필요" if score >= .65 else "미매핑"}
    if overrides is not None:
        unknown = set(overrides) - set(sources)
        if unknown:
            raise ValueError(f"원본에 없는 매핑 열입니다: {', '.join(sorted(unknown))}")
        for source, target in overrides.items():
            if target and target not in aliases:
                if layout != "wide" or not re.fullmatch(r"(debit|credit)_(account|amount)_[1-9]\d*", target):
                    raise ValueError(f"지원하지 않는 표준 열입니다: {target}")
            selected.pop(source, None)
            if target:
                selected[source] = target
            rows[source].update(standard_column=target or None, status="자동 확정" if target else "미매핑", matched_alias="사용자 지정", confidence=100.0 if target else 0.0)
    targets = list(selected.values())
    if len(targets) != len(set(targets)):
        raise ValueError("같은 표준 열에 여러 원본 열이 연결됐습니다. 매핑을 수정해 주세요.")
    return pd.DataFrame([rows[source] for source in sources], columns=["source_column", "standard_column", "matched_alias", "confidence", "status"])


def mapping_profile(mapping: dict[str, str | None], company: str, layout: str) -> bytes:
    """다음 파일에 재사용할 회사별 매핑 JSON을 생성한다."""
    return json.dumps({"version": 1, "company": company, "layout": layout, "mapping": mapping}, ensure_ascii=False, indent=2).encode("utf-8")


def read_mapping_profile(content: bytes) -> dict[str, Any]:
    """매핑 JSON의 구조를 검사하고 반환한다."""
    try:
        profile = json.loads(content)
    except (ValueError, UnicodeError) as error:
        raise ValueError("올바른 UTF-8 매핑 JSON 파일을 선택해 주세요.") from error
    if not isinstance(profile, dict) or profile.get("version") != 1 or profile.get("layout") not in {"wide", "vertical"} or not isinstance(profile.get("mapping"), dict):
        raise ValueError("지원하지 않는 매핑 설정 형식입니다.")
    if any(not isinstance(k, str) or (v is not None and not isinstance(v, str)) for k, v in profile["mapping"].items()):
        raise ValueError("매핑의 원본·표준 열 이름은 문자열이어야 합니다.")
    return profile


def print_mapping_result(mapping_result):
    """
    열 매핑 결과를 터미널에 보기 좋은 형태로 출력한다.
    """
    print("\n열 이름 자동 매핑 결과\n")
    print(mapping_result.to_string(index=False))

    status_summary = (
        mapping_result["status"]
        .value_counts()
        .to_dict()
    )

    print("\n매핑 상태 요약")
    print(status_summary)


def main(file_path):
    """
    엑셀 구조를 분석한 뒤 시트별로 열 자동 매핑을 실행한다.
    """
    analysis_result = analyze_excel_file(file_path)

    print(f"\n분석 파일: {analysis_result['file_name']}")

    for sheet_name, sheet_result in analysis_result["sheets"].items():
        print(f"\n[시트: {sheet_name}]")

        mapping_result = map_columns(
            sheet_result["columns"]
        )

        print_mapping_result(mapping_result)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(
            "사용 방법: "
            "python src/column_mapper.py 분석할_엑셀파일.xlsx"
        )
        sys.exit(1)

    main(sys.argv[1])
    