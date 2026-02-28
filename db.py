import pandas as pd
import streamlit as st
import json
import hashlib
from sqlalchemy import text
from config import get_admin_bootstrap

# ── 1. 연결 설정 ──
conn = st.connection(
    "postgresql",
    type="sql",
    pool_size=5,
    max_overflow=0,
    pool_recycle=300,
    pool_pre_ping=False,
    connect_args={"sslmode": "require"}
)

def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()

# ── 2. DB 초기화 함수 ──
def init_db():
    with conn.session as s:
        s.execute(text("SELECT 1"))

        s.execute(text("CREATE TABLE IF NOT EXISTS system_config (key TEXT PRIMARY KEY, value TEXT)"))
        s.execute(text("INSERT INTO system_config (key, value) VALUES ('status', 'NORMAL') ON CONFLICT (key) DO NOTHING"))

        s.execute(text("""
            CREATE TABLE IF NOT EXISTS approved_users (
                student_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                role TEXT DEFAULT 'member',
                status TEXT DEFAULT 'PENDING',
                password_hash TEXT,
                permissions TEXT,
                security_question TEXT,
                security_answer_hash TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))

        s.execute(text("""
            CREATE TABLE IF NOT EXISTS projects (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))

        s.execute(text("""
            CREATE TABLE IF NOT EXISTS members (
                id SERIAL PRIMARY KEY,
                project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                student_id TEXT,
                deposit_amount INTEGER DEFAULT 0,
                paid_date TEXT,
                note TEXT
            )
        """))

        s.execute(text("""
            CREATE TABLE IF NOT EXISTS budget_entries (
                id SERIAL PRIMARY KEY,
                project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
                entry_date TEXT,
                source_type TEXT,
                contributor_name TEXT,
                amount INTEGER,
                note TEXT,
                extra_label TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))

        s.execute(text("ALTER TABLE budget_entries ADD COLUMN IF NOT EXISTS extra_label TEXT"))

        s.execute(text("""
            CREATE TABLE IF NOT EXISTS expenses (
                id SERIAL PRIMARY KEY,
                project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
                date TEXT,
                item TEXT,
                amount INTEGER,
                category TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))

        s.execute(text("""
            CREATE TABLE IF NOT EXISTS reset_logs (
                id SERIAL PRIMARY KEY,
                student_id TEXT,
                name TEXT,
                reset_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                reset_by TEXT,
                is_read INTEGER DEFAULT 0
            )
        """))

        s.execute(text("""
            CREATE TABLE IF NOT EXISTS receipt_images (
                id SERIAL PRIMARY KEY,
                project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
                expense_id INTEGER REFERENCES expenses(id) ON DELETE CASCADE,
                filename TEXT,
                filepath TEXT,
                description TEXT,
                uploaded_by TEXT,
                uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))

        s.execute(text("""
            CREATE TABLE IF NOT EXISTS accounts (
                id SERIAL PRIMARY KEY,
                code TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                type TEXT NOT NULL
            )
        """))

        s.execute(text("""
            CREATE TABLE IF NOT EXISTS journal_entries (
                id SERIAL PRIMARY KEY,
                project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
                tx_date TEXT,
                description TEXT,
                source_kind TEXT,
                created_by TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))

        s.execute(text("""
            CREATE TABLE IF NOT EXISTS journal_lines (
                id SERIAL PRIMARY KEY,
                journal_entry_id INTEGER REFERENCES journal_entries(id) ON DELETE CASCADE,
                account_id INTEGER REFERENCES accounts(id),
                debit INTEGER DEFAULT 0,
                credit INTEGER DEFAULT 0,
                memo TEXT
            )
        """))

        s.execute(text("""
            CREATE TABLE IF NOT EXISTS audit_logs (
                id SERIAL PRIMARY KEY,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                action TEXT,
                details TEXT,
                user_mode TEXT,
                ip_address TEXT,
                device_info TEXT,
                operator_name TEXT
            )
        """))

        s.commit()

    # ── 계정 코드 시드 데이터 ──
    account_seed = [
        ("1100", "Cash_Operating", "ASSET"),
        ("1110", "Cash_Reserve", "ASSET"),
        ("1200", "AR_JacketBuyers", "ASSET"),
        ("4100", "Income_SchoolBudget", "INCOME"),
        ("4110", "Income_ReserveIn", "INCOME"),
        ("4120", "Income_StudentDues", "INCOME"),
        ("5100", "Expense_General", "EXPENSE"),
        ("5110", "Expense_JacketMaking", "EXPENSE"),
    ]
    for code, name, acc_type in account_seed:
        run_query(
            "INSERT INTO accounts (code, name, type) VALUES (:code, :name, :type) ON CONFLICT (code) DO NOTHING",
            {"code": code, "name": name, "type": acc_type}
        )

    # ── 관리자 계정 자동 생성 ──
    admin_sid, admin_name, admin_password = get_admin_bootstrap()
    admin_password_hash = _hash_password(admin_password) if admin_password else None
    admin_permissions = json.dumps([
        "can_view", "can_edit", "can_manage_members",
        "can_export", "can_archive", "can_delete_project", "can_upload_receipt"
    ])

    run_query("""
        INSERT INTO approved_users (student_id, name, role, status, password_hash, permissions)
        VALUES (:sid, :name, 'treasurer', 'APPROVED', :pw, :perm)
        ON CONFLICT (student_id) DO UPDATE
        SET name = EXCLUDED.name, password_hash = EXCLUDED.password_hash, permissions = EXCLUDED.permissions
    """, {"sid": admin_sid, "name": admin_name, "pw": admin_password_hash, "perm": admin_permissions})

# ── 3. 데이터 조작 함수 ──
def run_query(query: str, params=None, fetch: bool = False):
    try:
        if fetch:
            return conn.query(query, params=params, ttl=30)
        else:
            with conn.session as s:
                s.execute(text(query), params)
                s.commit()
            st.cache_data.clear()
    except Exception as e:
        st.error(f"❌ DB 에러: {e}")
        return None

def get_all_data(table_name: str) -> pd.DataFrame:
    allowed = {"projects", "members", "budget_entries", "expenses", "approved_users"}
    if table_name not in allowed:
        return pd.DataFrame()
    return conn.query(f"SELECT * FROM {table_name}", ttl=30)

# ── 4. 장부 조회 함수 ──
def get_ledger(project_id: int) -> pd.DataFrame:
    query = """
        SELECT entry_date AS transaction_date, created_at AS recorded_at, '수입' AS type,
        CASE source_type WHEN 'student_dues' THEN contributor_name || ' 회비'
        ELSE COALESCE(contributor_name, '') || ' ' || COALESCE(note, '') END AS description,
        amount AS amount
        FROM budget_entries WHERE project_id = :pid
        UNION ALL
        SELECT date AS transaction_date, created_at AS recorded_at, '지출' AS type,
        item || ' (' || COALESCE(category, '기타') || ')' AS description,
        -amount AS amount
        FROM expenses WHERE project_id = :pid
        ORDER BY transaction_date ASC, recorded_at ASC
    """
    return conn.query(query, params={"pid": project_id}, ttl=30)
