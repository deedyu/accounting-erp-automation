"""분개장을 날짜별 차변·대변 좌우형 대조표로 변환한다."""

from pathlib import Path
import sys
from typing import Any

if __name__ == "__main__" and not __package__:
    from _bootstrap import configure_script_imports
    configure_script_imports(__file__)

from src.journal_values import code, money, date_value, pair_columns

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ACCOUNTS_PATH = PROJECT_ROOT / "data" / "master" / "accounts.csv"


def is_empty(value):
    """결측값이나 공백인지 확인한다."""
    return pd.isna(value) or str(value).strip() == ""


def get_account_name(account_value: Any, account_name_map: dict[str, str]) -> str:
    """문자 계정코드를 보존하여 계정명을 찾는다."""
    return account_name_map.get(code(account_value), "알 수 없음") if code(account_value) else ""


def display_amount(value: Any) -> int | None:
    """장부 표시용 금액을 읽고 잘못된 금액은 결측으로 남긴다."""
    try:
        return money(value)
    except ValueError:
        return None


def make_account_pairs(row: pd.Series, side: str, account_name_map: dict[str, str]) -> list[dict[str, Any]]:
    """모든 계정 쌍을 원본 순서대로 장부 표시용 목록으로 만든다."""
    pairs = []
    for account_column, amount_column in pair_columns(row.index, side):
        account, raw = row.get(account_column), row.get(amount_column)
        amount = display_amount(raw)
        if not code(account) and (is_empty(raw) or amount == 0):
            continue
        pairs.append({"account_code": code(account), "account_name": get_account_name(account, account_name_map), "amount": amount})
    return pairs


def build_side_by_side_ledger(
    classified_journal,
    accounts
):
    """
    차변과 대변을 한 화면에서 좌우로 비교할 수 있는 표를 만든다.
    """
    account_name_map = dict(
        zip(
            accounts["account_code"].apply(code),
            accounts["account_name"]
        )
    )

    ledger_rows = []

    journal = classified_journal.copy()
    journal["transaction_date"] = journal["transaction_date"].apply(date_value)

    journal = journal.sort_values(
        by=[
            "transaction_date",
            "voucher_id"
        ],
        na_position="last"
    )

    for _, row in journal.iterrows():
        debit_pairs = make_account_pairs(
            row,
            "debit",
            account_name_map
        )
        credit_pairs = make_account_pairs(
            row,
            "credit",
            account_name_map
        )

        debit_total = sum(
            (pair["amount"] or 0)
            for pair in debit_pairs
        )
        credit_total = sum(
            (pair["amount"] or 0)
            for pair in credit_pairs
        )
        difference = debit_total - credit_total

        pair_count = max(
            len(debit_pairs),
            len(credit_pairs),
            1
        )

        for pair_index in range(pair_count):
            debit = (
                debit_pairs[pair_index]
                if pair_index < len(debit_pairs)
                else {}
            )
            credit = (
                credit_pairs[pair_index]
                if pair_index < len(credit_pairs)
                else {}
            )

            ledger_rows.append(
                {
                    "transaction_date": row[
                        "transaction_date"
                    ],
                    "voucher_id": row["voucher_id"],
                    "line_pair": pair_index + 1,
                    "transaction_type": row[
                        "transaction_type"
                    ],
                    "department_code": row[
                        "department_code"
                    ],
                    "partner_code": row[
                        "partner_code"
                    ],
                    "description": row["description"],
                    "debit_account_code": debit.get(
                        "account_code"
                    ),
                    "debit_account_name": debit.get(
                        "account_name",
                        ""
                    ),
                    "debit_amount": debit.get(
                        "amount",
                        0
                    ),
                    "credit_account_code": credit.get(
                        "account_code"
                    ),
                    "credit_account_name": credit.get(
                        "account_name",
                        ""
                    ),
                    "credit_amount": credit.get(
                        "amount",
                        0
                    ),
                    "voucher_debit_total": debit_total,
                    "voucher_credit_total": credit_total,
                    "difference": difference,
                    "balance_status": (
                        "일치"
                        if difference == 0
                        else "불일치"
                    ),
                    "processing_status": row[
                        "processing_status"
                    ],
                    "error_types": row["error_types"]
                }
            )

    return pd.DataFrame(ledger_rows, columns=["transaction_date", "voucher_id", "line_pair", "transaction_type", "department_code", "partner_code", "description", "debit_account_code", "debit_account_name", "credit_account_code", "credit_account_name", "debit_amount", "credit_amount", "voucher_debit_total", "voucher_credit_total", "difference", "balance_status", "processing_status", "error_types"])


def build_daily_balance_summary(classified_journal: pd.DataFrame) -> pd.DataFrame:
    """정수 원 단위로 날짜별 합계를 계산하고 해석 불가 금액 수를 표시한다."""
    journal = classified_journal.copy()
    journal["transaction_date"] = journal["transaction_date"].apply(date_value)
    invalid_counts = [0] * len(journal)
    for side in ["debit", "credit"]:
        totals = []
        for i, (_, row) in enumerate(journal.iterrows()):
            total = 0
            for _, amount_column in pair_columns(journal.columns, side):
                raw = row.get(amount_column)
                amount = display_amount(raw)
                if amount is None and not is_empty(raw):
                    invalid_counts[i] += 1
                total += amount or 0
            totals.append(total)
        journal[f"{side}_total"] = pd.Series(totals, index=journal.index, dtype=object)
    journal["unparsed_amount_count"] = invalid_counts
    journal["_count_key"] = journal.get("_row_id", journal["voucher_id"])
    summary = journal.dropna(subset=["transaction_date"]).groupby("transaction_date", sort=True).agg(
        transaction_count=("_count_key", "nunique"), debit_total=("debit_total", "sum"),
        credit_total=("credit_total", "sum"), unparsed_amount_count=("unparsed_amount_count", "sum"),
    ).reset_index()
    summary["difference"] = summary["debit_total"] - summary["credit_total"]
    summary["balance_status"] = ["확인 필요" if n else "일치" if d == 0 else "불일치" for d, n in zip(summary["difference"], summary["unparsed_amount_count"])]
    return summary


def build_monthly_balance_summary(daily_summary: pd.DataFrame, journal: pd.DataFrame | None = None) -> pd.DataFrame:
    """
    월 전체 차변·대변 합계와 차액을 계산한다.
    """
    debit_total = daily_summary["debit_total"].sum()
    credit_total = daily_summary["credit_total"].sum()
    transaction_count = int(daily_summary["transaction_count"].sum())
    unparsed = int(daily_summary.get("unparsed_amount_count", pd.Series(dtype=int)).sum())
    undated = 0
    if journal is not None:
        transaction_count = len(journal)
        undated = int(journal["transaction_date"].apply(date_value).isna().sum())
        values = {}
        unparsed = 0
        for side in ["debit", "credit"]:
            amounts = [row.get(column) for _, row in journal.iterrows() for _, column in pair_columns(journal.columns, side)]
            values[side] = sum(display_amount(v) or 0 for v in amounts)
            unparsed += sum(display_amount(v) is None and not is_empty(v) for v in amounts)
        debit_total, credit_total = values["debit"], values["credit"]
    difference = debit_total - credit_total

    return pd.DataFrame(
        [
            {
                "transaction_count": transaction_count,
                "unparsed_amount_count": unparsed,
                "undated_transaction_count": undated,
                "debit_total": debit_total,
                "credit_total": credit_total,
                "difference": difference,
                "balance_status": (
                    "확인 필요" if unparsed else "일치"
                    if difference == 0
                    else "불일치"
                )
            }
        ]
    )


def main(transaction_status_path):
    """저장된 검증 결과로 날짜별 대조표를 생성한다."""
    transaction_status_path = Path(
        transaction_status_path
    )

    classified_journal = pd.read_csv(
        transaction_status_path
    )
    accounts = pd.read_csv(ACCOUNTS_PATH)

    ledger = build_side_by_side_ledger(
        classified_journal,
        accounts
    )

    daily_summary = build_daily_balance_summary(
        classified_journal
    )

    monthly_summary = build_monthly_balance_summary(
        daily_summary
    )

    output_directory = transaction_status_path.parent

    ledger.to_csv(
        output_directory / "side_by_side_ledger.csv",
        index=False,
        encoding="utf-8-sig"
    )

    daily_summary.to_csv(
        output_directory / "daily_balance_summary.csv",
        index=False,
        encoding="utf-8-sig"
    )

    monthly_summary.to_csv(
        output_directory / "monthly_balance_summary.csv",
        index=False,
        encoding="utf-8-sig"
    )

    print("\n날짜별 차변·대변 대조표 생성 완료")
    print(f"대조표 행 수: {len(ledger)}")

    print("\n날짜별 합계")
    print(daily_summary.to_string(index=False))

    print("\n월 전체 합계")
    print(monthly_summary.to_string(index=False))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(
            "사용 방법: "
            "python src/daily_ledger.py "
            "transaction_status.csv"
        )
        sys.exit(1)

    main(sys.argv[1])