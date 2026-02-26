# accounting/service.py
import sqlite3
from typing import Optional


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


def init_accounting_accounts(conn: sqlite3.Connection):
    conn.executemany(
        "INSERT OR IGNORE INTO accounts (code, name, type) VALUES (?, ?, ?)",
        ACCOUNT_SEED,
    )


def _account_id(conn: sqlite3.Connection, code: str) -> int:
    row = conn.execute("SELECT id FROM accounts WHERE code = ?", (code,)).fetchone()
    if not row:
        raise ValueError(f"Unknown account code: {code}")
    return int(row[0])


def _compose_desc(base: str, extra_label: str) -> str:
    extra = (extra_label or "").strip()
    if not extra:
        return base
    return f"{base} - {extra}"


def _post_journal(
    conn: sqlite3.Connection,
    project_id: int,
    tx_date: str,
    description: str,
    source_kind: str,
    created_by: str,
    debit_code: str,
    credit_code: str,
    amount: int,
    memo: str = "",
):
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO journal_entries (project_id, tx_date, description, source_kind, created_by)
        VALUES (?, ?, ?, ?, ?)
        """,
        (project_id, tx_date, description, source_kind, created_by),
    )
    je_id = int(cur.lastrowid)

    cur.execute(
        """
        INSERT INTO journal_lines (journal_entry_id, account_id, debit, credit, memo)
        VALUES (?, ?, ?, 0, ?)
        """,
        (je_id, _account_id(conn, debit_code), amount, memo),
    )
    cur.execute(
        """
        INSERT INTO journal_lines (journal_entry_id, account_id, debit, credit, memo)
        VALUES (?, ?, 0, ?, ?)
        """,
        (je_id, _account_id(conn, credit_code), amount, memo),
    )
    return je_id


def record_income_entry(
    conn: sqlite3.Connection,
    project_id: int,
    tx_date: str,
    source_type: str,
    actor_name: str,
    amount: int,
    note: str = "",
    extra_label: str = "",
) -> Optional[int]:
    if amount <= 0:
        return None

    # source_type: school_budget | reserve_fund | reserve_recovery | student_dues
    if source_type == "school_budget":
        return _post_journal(
            conn,
            project_id,
            tx_date,
            _compose_desc("학교/학과 지원금 입금", extra_label),
            "SCHOOL_BUDGET",
            actor_name,
            "1100",
            "4100",
            amount,
            note,
        )

    if source_type == "reserve_fund":
        return _post_journal(
            conn,
            project_id,
            tx_date,
            _compose_desc("예비비/이월금 유입", extra_label),
            "RESERVE_IN",
            actor_name,
            "1110",
            "4110",
            amount,
            note,
        )

    if source_type == "reserve_recovery":
        # 회수/정산 입금(예비비 복구): Dr Reserve Cash / Cr AR
        return _post_journal(
            conn,
            project_id,
            tx_date,
            _compose_desc("회수/정산 입금(예비비 복구)", extra_label),
            "RESERVE_RECOVERY",
            actor_name,
            "1110",
            "1200",
            amount,
            note,
        )

    if source_type == "student_dues":
        return _post_journal(
            conn,
            project_id,
            tx_date,
            _compose_desc("학생회비 입금", extra_label),
            "STUDENT_DUES",
            actor_name,
            "1100",
            "4120",
            amount,
            note,
        )

    return None


def record_expense_entry(
    conn: sqlite3.Connection,
    project_id: int,
    tx_date: str,
    category: str,
    item: str,
    amount: int,
    actor_name: str,
):
    if amount <= 0:
        return None

    if category == "과잠 제작비(예비비 선지출)":
        # 회수 예정 선지출: Dr AR / Cr Reserve Cash
        return _post_journal(
            conn,
            project_id,
            tx_date,
            f"{item} 선지출",
            "JACKET_ADVANCE",
            actor_name,
            "1200",
            "1110",
            amount,
            item,
        )

    # 일반 지출: Dr Expense / Cr Operating Cash
    expense_code = "5110" if "과잠" in category else "5100"
    return _post_journal(
        conn,
        project_id,
        tx_date,
        f"{item} 지출",
        "EXPENSE",
        actor_name,
        expense_code,
        "1100",
        amount,
        category,
    )
