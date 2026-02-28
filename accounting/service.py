import pandas as pd
from typing import Optional
from sqlalchemy import text  # 깐깐해진 SQLAlchemy 달래기용
from db import run_query, conn

ACCOUNT_SEED = [
    ("1100", "Cash:Operating", "ASSET"),
    ("1110", "Cash:Reserve", "ASSET"),
    ("1200", "AR:JacketBuyers", "ASSET"),
    ("4100", "Income:SchoolBudget", "INCOME"),
    ("4110", "Income:ReserveIn", "INCOME"),
    ("4120", "Income:StudentDues", "INCOME"),
    ("5100", "Expense:General", "EXPENSE"),
    ("5110", "Expense:JacketMaking", "EXPENSE"),
]

def init_accounting_accounts():
    """초기 계정 과목 설정 (PostgreSQL ON CONFLICT 문법)"""
    for code, name, acc_type in ACCOUNT_SEED:
        # run_query 내부에서 text() 처리를 해주므로 여기선 그냥 문자열 넘겨도 됨
        run_query(
            """
            INSERT INTO accounts (code, name, type) 
            VALUES (:code, :name, :type)
            ON CONFLICT (code) DO NOTHING
            """,
            {"code": code, "name": name, "type": acc_type}
        )

def _account_id(code: str) -> int:
    """계정 코드(예: 1100)로 DB의 id(PK)를 찾아옴"""
    df = run_query("SELECT id FROM accounts WHERE code = :code", {"code": code}, fetch=True)
    if df is None or df.empty:
        raise ValueError(f"Unknown account code: {code}")
    return int(df.iloc[0]["id"])

def _compose_desc(base: str, extra_label: str) -> str:
    """적요(description) 문자열을 예쁘게 조합해주는 헬퍼 함수"""
    extra = (extra_label or "").strip()
    if not extra:
        return base
    return f"{base} - {extra}"

def _post_journal(project_id: int, tx_date: str, description: str, source_kind: str, 
                  created_by: str, debit_code: str, credit_code: str, amount: int, memo: str = ""):
    """복식부기 핵심 로직: 차변과 대변을 동시에 기록"""
    with conn.session as s:
        # 1. 분개장(journal_entries) 입력 및 생성된 ID(PK) 반환 (RETURNING id)
        res = s.execute(
            text("""
            INSERT INTO journal_entries (project_id, tx_date, description, source_kind, created_by)
            VALUES (:pid, :date, :desc, :kind, :user)
            RETURNING id
            """),
            {"pid": project_id, "date": tx_date, "desc": description, "kind": source_kind, "user": created_by}
        )
        je_id = res.fetchone()[0]

        # 2. 차변(Debit) 입력
        s.execute(
            text("""
            INSERT INTO journal_lines (journal_entry_id, account_id, debit, credit, memo)
            VALUES (:je_id, :acc_id, :amount, 0, :memo)
            """),
            {"je_id": je_id, "acc_id": _account_id(debit_code), "amount": amount, "memo": memo}
        )
        
        # 3. 대변(Credit) 입력
        s.execute(
            text("""
            INSERT INTO journal_lines (journal_entry_id, account_id, debit, credit, memo)
            VALUES (:je_id, :acc_id, 0, :amount, :memo)
            """),
            {"je_id": je_id, "acc_id": _account_id(credit_code), "amount": amount, "memo": memo}
        )
        
        # 트랜잭션 확정 (하나라도 실패하면 롤백됨!)
        s.commit()
        return je_id

def record_income_entry(
    project_id: int,
    tx_date: str,
    source_type: str,
    actor_name: str,
    amount: int,
    note: str = "",
    extra_label: str = "",
) -> Optional[int]:
    """수입을 기록하는 함수 (conn 파라미터 삭제됨)"""
    if amount <= 0:
        return None

    # source_type: school_budget | reserve_fund | reserve_recovery | student_dues
    if source_type == "school_budget":
        return _post_journal(project_id, tx_date, _compose_desc("학교/학과 지원금 입금", extra_label), "SCHOOL_BUDGET", actor_name, "1100", "4100", amount, note)
    
    if source_type == "reserve_fund":
        return _post_journal(project_id, tx_date, _compose_desc("예비비/이월금 유입", extra_label), "RESERVE_IN", actor_name, "1110", "4110", amount, note)
    
    if source_type == "reserve_recovery":
        # 회수/정산 입금(예비비 복구): Dr Reserve Cash / Cr AR
        return _post_journal(project_id, tx_date, _compose_desc("회수/정산 입금(예비비 복구)", extra_label), "RESERVE_RECOVERY", actor_name, "1110", "1200", amount, note)
    
    if source_type == "student_dues":
        return _post_journal(project_id, tx_date, _compose_desc("학생회비 입금", extra_label), "STUDENT_DUES", actor_name, "1100", "4120", amount, note)

    return None

def record_expense_entry(
    project_id: int,
    tx_date: str,
    category: str,
    item: str,
    amount: int,
    actor_name: str,
):
    """지출을 기록하는 함수 (conn 파라미터 삭제됨)"""
    if amount <= 0:
        return None

    if category == "과잠 제작비(예비비 선지출)":
        # 회수 예정 선지출: Dr AR / Cr Reserve Cash
        return _post_journal(project_id, tx_date, f"{item} 선지출", "JACKET_ADVANCE", actor_name, "1200", "1110", amount, item)

    # 일반 지출: Dr Expense / Cr Operating Cash
    expense_code = "5110" if "과잠" in category else "5100"
    return _post_journal(project_id, tx_date, f"{item} 지출", "EXPENSE", actor_name, expense_code, "1100", amount, category)
