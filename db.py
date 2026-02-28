import pandas as pd
import streamlit as st
import json
import hashlib
from sqlalchemy import text
from config import get_admin_bootstrap

# ── 1. 연결 설정 (Azure SQL용으로 이름 변경) ──
# secrets.toml 의 [connections.sql] 설정을 자동으로 바라보게 "sql" 로만 지정
conn = st.connection(
    "sql",
    type="sql",
    pool_size=5,
    max_overflow=0,
    pool_recycle=300,
    pool_pre_ping=True
)

def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()

# ── 2. DB 초기화 함수 (Azure T-SQL 문법 적용) ──
def init_db():
    with conn.session as s:
        s.execute(text("SELECT 1"))

        s.execute(text("""
            IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='system_config' AND xtype='U')
            CREATE TABLE system_config ([key] NVARCHAR(50) PRIMARY KEY, [value] NVARCHAR(MAX))
        """))
        s.execute(text("""
            IF NOT EXISTS (SELECT 1 FROM system_config WHERE [key] = 'status')
            INSERT INTO system_config ([key], [value]) VALUES ('status', 'NORMAL')
        """))

        s.execute(text("""
            IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='approved_users' AND xtype='U')
            CREATE TABLE approved_users (
                student_id NVARCHAR(50) PRIMARY KEY,
                name NVARCHAR(100) NOT NULL,
                role NVARCHAR(50) DEFAULT 'member',
                status NVARCHAR(50) DEFAULT 'PENDING',
                password_hash NVARCHAR(MAX),
                permissions NVARCHAR(MAX),
                security_question NVARCHAR(MAX),
                security_answer_hash NVARCHAR(MAX),
                created_at DATETIME DEFAULT GETDATE()
            )
        """))

        s.execute(text("""
            IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='projects' AND xtype='U')
            CREATE TABLE projects (
                id INT IDENTITY(1,1) PRIMARY KEY,
                name NVARCHAR(200) NOT NULL UNIQUE,
                created_at DATETIME DEFAULT GETDATE()
            )
        """))

        s.execute(text("""
            IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='members' AND xtype='U')
            CREATE TABLE members (
                id INT IDENTITY(1,1) PRIMARY KEY,
                project_id INT REFERENCES projects(id) ON DELETE CASCADE,
                name NVARCHAR(100) NOT NULL,
                student_id NVARCHAR(50),
                deposit_amount INT DEFAULT 0,
                paid_date NVARCHAR(50),
                note NVARCHAR(MAX)
            )
        """))

        s.execute(text("""
            IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='budget_entries' AND xtype='U')
            CREATE TABLE budget_entries (
                id INT IDENTITY(1,1) PRIMARY KEY,
                project_id INT REFERENCES projects(id) ON DELETE CASCADE,
                entry_date NVARCHAR(50),
                source_type NVARCHAR(50),
                contributor_name NVARCHAR(100),
                amount INT,
                note NVARCHAR(MAX),
                extra_label NVARCHAR(100),
                created_at DATETIME DEFAULT GETDATE()
            )
        """))
        
        # 컬럼 추가 로직 (MS SQL 방식)
        s.execute(text("""
            IF COL_LENGTH('budget_entries', 'extra_label') IS NULL
            ALTER TABLE budget_entries ADD extra_label NVARCHAR(100)
        """))

        s.execute(text("""
            IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='expenses' AND xtype='U')
            CREATE TABLE expenses (
                id INT IDENTITY(1,1) PRIMARY KEY,
                project_id INT REFERENCES projects(id) ON DELETE CASCADE,
                date NVARCHAR(50),
                item NVARCHAR(200),
                amount INT,
                category NVARCHAR(100),
                created_at DATETIME DEFAULT GETDATE()
            )
        """))

        s.execute(text("""
            IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='reset_logs' AND xtype='U')
            CREATE TABLE reset_logs (
                id INT IDENTITY(1,1) PRIMARY KEY,
                student_id NVARCHAR(50),
                name NVARCHAR(100),
                reset_at DATETIME DEFAULT GETDATE(),
                reset_by NVARCHAR(50),
                is_read INT DEFAULT 0
            )
        """))

        s.execute(text("""
            IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='receipt_images' AND xtype='U')
            CREATE TABLE receipt_images (
                id INT IDENTITY(1,1) PRIMARY KEY,
                project_id INT REFERENCES projects(id) ON DELETE CASCADE,
                expense_id INT REFERENCES expenses(id) ON DELETE CASCADE,
                filename NVARCHAR(MAX),
                filepath NVARCHAR(MAX),
                description NVARCHAR(MAX),
                uploaded_by NVARCHAR(100),
                uploaded_at DATETIME DEFAULT GETDATE()
            )
        """))

        s.execute(text("""
            IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='accounts' AND xtype='U')
            CREATE TABLE accounts (
                id INT IDENTITY(1,1) PRIMARY KEY,
                code NVARCHAR(50) UNIQUE NOT NULL,
                name NVARCHAR(100) NOT NULL,
                type NVARCHAR(50) NOT NULL
            )
        """))

        s.execute(text("""
            IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='journal_entries' AND xtype='U')
            CREATE TABLE journal_entries (
                id INT IDENTITY(1,1) PRIMARY KEY,
                project_id INT REFERENCES projects(id) ON DELETE CASCADE,
                tx_date NVARCHAR(50),
                description NVARCHAR(MAX),
                source_kind NVARCHAR(50),
                created_by NVARCHAR(100),
                created_at DATETIME DEFAULT GETDATE()
            )
        """))

        s.execute(text("""
            IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='journal_lines' AND xtype='U')
            CREATE TABLE journal_lines (
                id INT IDENTITY(1,1) PRIMARY KEY,
                journal_entry_id INT REFERENCES journal_entries(id) ON DELETE CASCADE,
                account_id INT REFERENCES accounts(id),
                debit INT DEFAULT 0,
                credit INT DEFAULT 0,
                memo NVARCHAR(MAX)
            )
        """))

        s.execute(text("""
            IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='audit_logs' AND xtype='U')
            CREATE TABLE audit_logs (
                id INT IDENTITY(1,1) PRIMARY KEY,
                timestamp DATETIME DEFAULT GETDATE(),
                action NVARCHAR(100),
                details NVARCHAR(MAX),
                user_mode NVARCHAR(50),
                ip_address NVARCHAR(100),
                device_info NVARCHAR(MAX),
                operator_name NVARCHAR(100)
            )
        """))

        s.commit()

    # ── 계정 코드 시드 데이터 (IF NOT EXISTS로 변경) ──
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
            """
            IF NOT EXISTS (SELECT 1 FROM accounts WHERE code = :code)
            INSERT INTO accounts (code, name, type) VALUES (:code, :name, :type)
            """,
            {"code": code, "name": name, "type": acc_type}
        )

    # ── 관리자 계정 자동 생성 (MERGE 대신 IF/ELSE 구조 사용) ──
    admin_sid, admin_name, admin_password = get_admin_bootstrap()
    admin_password_hash = _hash_password(admin_password) if admin_password else None
    admin_permissions = json.dumps([
        "can_view", "can_edit", "can_manage_members",
        "can_export", "can_archive", "can_delete_project", "can_upload_receipt"
    ])

    run_query("""
        IF EXISTS (SELECT 1 FROM approved_users WHERE student_id = :sid)
            UPDATE approved_users
            SET name = :name, password_hash = :pw, permissions = :perm
            WHERE student_id = :sid
        ELSE
            INSERT INTO approved_users (student_id, name, role, status, password_hash, permissions)
            VALUES (:sid, :name, 'treasurer', 'APPROVED', :pw, :perm)
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

# ── 4. 장부 조회 함수 (CONCAT 적용) ──
def get_ledger(project_id: int) -> pd.DataFrame:
    query = """
        SELECT entry_date AS transaction_date, created_at AS recorded_at, '수입' AS type,
        CASE source_type WHEN 'student_dues' THEN CONCAT(contributor_name, ' 회비')
        ELSE CONCAT(ISNULL(contributor_name, ''), ' ', ISNULL(note, '')) END AS description,
        amount AS amount
        FROM budget_entries WHERE project_id = :pid
        UNION ALL
        SELECT date AS transaction_date, created_at AS recorded_at, '지출' AS type,
        CONCAT(item, ' (', ISNULL(category, '기타'), ')') AS description,
        -amount AS amount
        FROM expenses WHERE project_id = :pid
        ORDER BY transaction_date ASC, recorded_at ASC
    """
    return conn.query(query, params={"pid": project_id}, ttl=30)
