-- 1. 전체 처리 상태 요약
SELECT
    processing_status,
    COUNT(*) AS transaction_count,
    SUM(total_amount) AS total_amount,
    ROUND(
        COUNT(*) * 100.0
        / (
            SELECT COUNT(*)
            FROM staging_transactions
        ),
        1
    ) AS status_rate
FROM staging_transactions
GROUP BY processing_status
ORDER BY transaction_count DESC;


-- 2. 오류 유형별 발생 건수
SELECT
    error_type,
    COUNT(*) AS error_count,
    ROUND(
        COUNT(*) * 100.0
        / (
            SELECT COUNT(*)
            FROM validation_errors
        ),
        1
    ) AS error_rate
FROM validation_errors
GROUP BY error_type
ORDER BY error_count DESC, error_type;


-- 3. 부서별 검토 필요 현황
SELECT
    st.department_code,
    COALESCE(
        d.department_name,
        '미등록 부서'
    ) AS department_name,
    COUNT(*) AS transaction_count,
    SUM(
        CASE
            WHEN st.processing_status = '검토 필요'
            THEN 1
            ELSE 0
        END
    ) AS review_count,
    ROUND(
        SUM(
            CASE
                WHEN st.processing_status = '검토 필요'
                THEN 1
                ELSE 0
            END
        ) * 100.0 / COUNT(*),
        1
    ) AS review_rate
FROM staging_transactions AS st
LEFT JOIN departments AS d
    ON st.department_code = d.department_code
GROUP BY
    st.department_code,
    d.department_name
ORDER BY review_rate DESC, transaction_count DESC;


-- 4. 거래 유형별 처리 현황
SELECT
    transaction_type,
    COUNT(*) AS transaction_count,
    SUM(
        CASE
            WHEN processing_status = '입력 가능'
            THEN 1
            ELSE 0
        END
    ) AS ready_count,
    SUM(
        CASE
            WHEN processing_status = '검토 필요'
            THEN 1
            ELSE 0
        END
    ) AS review_count,
    ROUND(
        SUM(
            CASE
                WHEN processing_status = '검토 필요'
                THEN 1
                ELSE 0
            END
        ) * 100.0 / COUNT(*),
        1
    ) AS review_rate
FROM staging_transactions
GROUP BY transaction_type
ORDER BY transaction_count DESC;


-- 5. 일자별 처리 현황
SELECT
    transaction_date,
    COUNT(*) AS transaction_count,
    SUM(
        CASE
            WHEN processing_status = '입력 가능'
            THEN 1
            ELSE 0
        END
    ) AS ready_count,
    SUM(
        CASE
            WHEN processing_status = '검토 필요'
            THEN 1
            ELSE 0
        END
    ) AS review_count,
    SUM(total_amount) AS total_amount
FROM staging_transactions
GROUP BY transaction_date
ORDER BY transaction_date;


-- 6. 계정과목별 차변·대변 집계
SELECT
    jl.account_code,
    a.account_name,
    a.account_category,
    SUM(
        CASE
            WHEN jl.debit_credit_type = '차변'
            THEN jl.amount
            ELSE 0
        END
    ) AS debit_amount,
    SUM(
        CASE
            WHEN jl.debit_credit_type = '대변'
            THEN jl.amount
            ELSE 0
        END
    ) AS credit_amount,
    SUM(
        CASE
            WHEN jl.debit_credit_type = '차변'
            THEN jl.amount
            ELSE -jl.amount
        END
    ) AS net_amount
FROM journal_lines AS jl
INNER JOIN accounts AS a
    ON jl.account_code = a.account_code
GROUP BY
    jl.account_code,
    a.account_name,
    a.account_category
ORDER BY
    a.account_category,
    jl.account_code;


-- 7. 거래처별 검토 필요 현황
SELECT
    st.partner_code,
    COALESCE(
        p.partner_name,
        '미등록 거래처'
    ) AS partner_name,
    COUNT(*) AS transaction_count,
    SUM(
        CASE
            WHEN st.processing_status = '검토 필요'
            THEN 1
            ELSE 0
        END
    ) AS review_count,
    ROUND(
        SUM(
            CASE
                WHEN st.processing_status = '검토 필요'
                THEN 1
                ELSE 0
            END
        ) * 100.0 / COUNT(*),
        1
    ) AS review_rate
FROM staging_transactions AS st
LEFT JOIN partners AS p
    ON st.partner_code = p.partner_code
GROUP BY
    st.partner_code,
    p.partner_name
ORDER BY review_rate DESC, transaction_count DESC;


-- 8. 담당자 검토 대기열 상세 조회
SELECT
    st.voucher_id,
    st.transaction_date,
    st.transaction_type,
    COALESCE(
        d.department_name,
        st.department_code
    ) AS department,
    COALESCE(
        p.partner_name,
        st.partner_code
    ) AS partner,
    st.description,
    st.total_amount,
    ve.error_column,
    ve.error_type,
    ve.detail
FROM staging_transactions AS st
INNER JOIN validation_errors AS ve
    ON st.voucher_id = ve.voucher_id
LEFT JOIN departments AS d
    ON st.department_code = d.department_code
LEFT JOIN partners AS p
    ON st.partner_code = p.partner_code
WHERE st.processing_status = '검토 필요'
ORDER BY
    st.transaction_date,
    st.voucher_id;


-- 9. ERP 전표별 차변·대변 재검증
SELECT
    ev.voucher_id,
    ev.transaction_date,
    SUM(
        CASE
            WHEN jl.debit_credit_type = '차변'
            THEN jl.amount
            ELSE 0
        END
    ) AS debit_amount,
    SUM(
        CASE
            WHEN jl.debit_credit_type = '대변'
            THEN jl.amount
            ELSE 0
        END
    ) AS credit_amount,
    SUM(
        CASE
            WHEN jl.debit_credit_type = '차변'
            THEN jl.amount
            ELSE -jl.amount
        END
    ) AS difference
FROM erp_vouchers AS ev
INNER JOIN journal_lines AS jl
    ON ev.voucher_id = jl.voucher_id
GROUP BY
    ev.voucher_id,
    ev.transaction_date
HAVING difference != 0
ORDER BY ev.voucher_id;