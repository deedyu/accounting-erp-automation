# SQLite 실행 이력 스키마

기본 DB: `data/processed/accounting_history.db`. 정의: `sql/history_schema.sql`.
기존 DB와 테이블을 DROP/DELETE하지 않고 automation_ 접두사 테이블을 추가합니다.

| 테이블 | 역할·키 |
|---|---|
| automation_runs | run_id PK, 처리 시각·파일명·시트·요약·결과 경로·장부 스냅샷 |
| automation_files | run_id PK/FK, SHA-256·원본 이름·선택 범위·원본/미매핑/분리 행 JSON |
| automation_mappings | (run_id, source_column) PK, 매핑·신뢰도·상태 |
| automation_vouchers | (run_id, row_id) PK, 원본 전표번호·행 번호·날짜·상태·전표 JSON |
| automation_errors | error_id PK, 실행/내부 행 FK, 원본 위치·심각도·오류 |
| automation_erp_lines | (run_id, voucher_id, line_no) PK, 실행/내부 행 FK, 계정코드 TEXT·금액 INTEGER |
| automation_daily_totals | (run_id, scope, transaction_date) PK, 전체/정상 합계 |

전표번호는 원본 값으로서 NULL도 저장할 수 있습니다. 오류 연결은 row_id로 수행하여 누락·중복 전표번호 때문에 저장이 실패하지 않습니다.
`sqlite3.Connection`의 하나의 트랜잭션 안에서 parameterized INSERT를 실행하고 커밋 전에 외래키 무결성을 확인합니다. pandas.to_sql의 테이블별 커밋에 의존하지 않습니다.
이력은 append 방식이며 조회는 mode=ro 연결을 사용합니다. 같은 원본 재실행도 서로 다른 run_id로 기록합니다.
