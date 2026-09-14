"""회계 분개장 ERP 입력 검증 전체 파이프라인 실행."""

from time import perf_counter

from journal_validator import main as run_validation
from prepare_erp_upload import main as run_erp_conversion
from load_database import main as run_database_loading
from export_dashboard_data import main as run_dashboard_export


# 실행할 작업의 이름과 함수를 처리 순서대로 정의
PIPELINE_STEPS = [
    ("1. 분개장 오류 검증", run_validation),
    ("2. ERP 업로드 데이터 변환", run_erp_conversion),
    ("3. SQLite 데이터베이스 적재", run_database_loading),
    ("4. Tableau 대시보드 데이터 생성", run_dashboard_export),
]


def run_step(step_name, step_function):
    """파이프라인의 한 단계를 실행하고 소요 시간을 출력."""

    print()
    print("=" * 60)
    print(f"{step_name} 시작")
    print("=" * 60)

    start_time = perf_counter()

    try:
        # 각 Python 파일에서 가져온 main 함수를 실행
        step_function()

    except Exception as error:
        print()
        print(f"[실패] {step_name}")
        print(f"오류 내용: {error}")

        # 오류가 발생하면 다음 단계로 넘어가지 않도록 중단
        raise

    elapsed_time = perf_counter() - start_time

    print()
    print(f"[완료] {step_name}")
    print(f"소요 시간: {elapsed_time:.2f}초")


def main():
    """전체 분개장 검증 및 ERP 변환 파이프라인 실행."""

    pipeline_start_time = perf_counter()

    print()
    print("회계 분개장 ERP 입력 검증 파이프라인 시작")

    # PIPELINE_STEPS에 작성된 순서대로 모든 작업 실행
    for step_name, step_function in PIPELINE_STEPS:
        run_step(step_name, step_function)

    total_elapsed_time = perf_counter() - pipeline_start_time

    print()
    print("=" * 60)
    print("전체 파이프라인 실행 완료")
    print(f"전체 소요 시간: {total_elapsed_time:.2f}초")
    print("=" * 60)


if __name__ == "__main__":
    main()