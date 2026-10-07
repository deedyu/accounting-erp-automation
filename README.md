# 회계 분개장 ERP 입력 검증 자동화

경영사무 인턴 당시 Excel 분개장 내용을 확인한 뒤 ERP에 직접 입력하는 업무를 하면서 만든 프로젝트입니다.

반복해서 확인하던 항목들을 Python으로 먼저 검증하고, 문제가 없는 전표만 ERP 업로드용 형식으로 바꾸도록 구현했습니다.

![CI](https://github.com/deedyu/accounting-erp-automation/actions/workflows/tests.yml/badge.svg)

## 구현 내용

전체 흐름은 아래와 같습니다.

```text
Excel 업로드
→ 파일 구조 및 열 이름 확인
→ 표준 컬럼으로 매핑
→ 회계 데이터 검증
→ 입력 가능 / 검토 필요 / 입력 불가 분류
→ ERP 업로드용 Excel·CSV·JSON 생성
→ SQLite에 실행 결과 저장
→ Streamlit에서 결과 확인
```

주요 검증 항목은 다음과 같습니다.

- 필수값 누락
- 계정과목·거래처·부서 코드 확인
- 차변·대변 금액 일치 여부
- 공급가액·부가세·총액 확인
- 증빙번호 중복
- 회계기간을 벗어난 날짜
- 금액 형식 및 음수·0원 정책

## 만들면서 바꾼 부분

처음에는 정해진 형식의 분개장만 처리하도록 만들었습니다.

그런데 실제 Excel 파일은 열 이름이나 순서가 다를 수 있다고 생각해서, 이후에는 열 별칭을 이용한 자동 매핑과 수동 수정 기능을 추가했습니다. 회사별로 수정한 매핑은 JSON으로 저장했다가 다시 불러올 수 있도록 했습니다.

또한 단순히 오류 여부만 표시하는 대신 전표를 `입력 가능`, `검토 필요`, `입력 불가`로 나누고, 입력 가능한 전표만 ERP용 데이터로 변환하도록 변경했습니다.

변환한 뒤에도 차변·대변 금액을 다시 확인하도록 해서 변환 과정에서 금액이 달라지지 않는지 한 번 더 검사합니다.

## 화면

![회계 분개장 ERP 입력 검증 대시보드](dashboard/accounting_erp_dashboard.png)

현재 Streamlit 화면에서는 파일 업로드부터 열 매핑, 검증 결과, 오류 내역, 일계표, ERP 변환 결과까지 확인할 수 있습니다.

## 테스트

기능을 추가하면서 기존 검증 결과가 바뀌는 문제를 확인하기 위해 pytest 테스트를 작성했습니다.

현재 테스트에는 다음 항목이 포함되어 있습니다.

- 정상 전표와 오류 전표
- 필수값·코드·금액·날짜 오류
- 증빙 중복
- 회계기간 시작일/종료일 경계
- -1원, 0원, 1원 등 금액 경계값
- ERP 변환 전후 금액 보존
- Excel 구조와 열 순서 변경
- SQLite 저장 및 실행 이력
- 전체 파이프라인 실행

```bash
python -m pytest -q
```

기존에 만든 500건의 가상 분개장도 회귀 테스트에 사용하고 있습니다.

이 데이터에는 직접 정의한 오류를 넣어 검증 로직을 확인했기 때문에, 해당 결과를 실제 기업 데이터 전체의 정확도로 해석하지는 않았습니다.

## 사용 기술

- Python 3.12
- pandas
- NumPy
- openpyxl
- SQLite
- Streamlit
- Tableau
- pytest
- Git / GitHub Actions

## 프로젝트 구조

```text
accounting-erp-automation/
├── app.py
├── config/
├── dashboard/
├── data/
├── docs/
├── notebooks/
├── sql/
├── src/
├── tests/
├── requirements.txt
└── requirements-dev.txt
```

주요 파일은 다음과 같습니다.

- `src/file_analyzer.py`: Excel 시트·헤더·범위 분석
- `src/column_mapper.py`: 열 이름 자동/수동 매핑
- `src/data_standardizer.py`: 입력 데이터 표준화
- `src/journal_validator.py`: 회계 검증
- `src/prepare_erp_upload.py`: ERP 업로드 형식 변환
- `src/adaptive_database.py`: SQLite 저장 및 실행 이력
- `src/daily_ledger.py`: 일계표 생성
- `src/dashboard.py`: 결과 화면 및 다운로드

## 실행 방법

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

테스트를 실행하려면:

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

## 현재 범위

현재는 실제 ERP에 자동으로 전표를 등록하지 않고, 업로드 가능한 파일을 만드는 단계까지 구현했습니다.

실제 ERP와 연결하려면 ERP 제품별 업로드 규격이나 API, 인증 방식, 승인 절차 등을 추가로 확인해야 합니다.

앞으로는 사용자 권한·승인 이력, ERP API 연동, 대용량 파일 처리 등을 확장할 수 있습니다.
