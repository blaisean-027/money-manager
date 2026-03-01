# db.py
"""
Azure SQL (MS SQL Server) + Streamlit Cloud + pymssql 안정 버전
- SQLAlchemy URL은 Secrets에서 가져옴
- 필요한 테이블 전부 생성
- system_config의 [key]/[value] 예약어 처리 완료
"""

import os
import json
import hashlib
import urllib.parse

import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from config import get_admin_bootstrap


# ─────────────────────────────────────────────
# Secrets helpers
# ─────────────────────────────────────────────
def _secret_get(*keys, default=None):
    for key in keys:
        # st.secrets 최상위 키
        try:
            if key in st.secrets:
                return st.secrets[key]
        except Exception:
            pass

        # 환경변수 fallback
        v = os.getenv(key)
        if v:
            return v
    return default


def _build_sqlalchemy_url() -> str:
    # 0) 가장 안정: 단일 키로 직접 URL 제공
    direct = _secret_get("SQLALCHEMY_DATABASE_URI", "DATABASE_URL", "AZURE_SQL_URL")
    if direct:
        return direct

    # 1) Streamlit connections
    try:
        if "connections" in st.secrets and "sql" in st.secrets["connections"]:
            cfg = st.secrets["connections"]["sql"]
            if isinstance(cfg, dict) and cfg.get("url"):
                return cfg["url"]
    except Exception:
        pass

    # 2) 개별 값 조합 (pymssql)
    server = _secret_get("AZURE_SQL_SERVER", "DB_HOST")
    database = _secret_get("AZURE_SQL_DATABASE", "DB_NAME")
    username = _secret_get("AZURE_SQL_USER", "DB_USER")
    password = _secret_get("AZURE_SQL_PASSWORD", "DB_PASSWORD")
    port = _secret_get("AZURE_SQL_PORT", "DB_PORT", default="1433")

    if not all([server, database, username, password]):
        raise RuntimeError("DB 접속 정보가 없습니다. Streamlit Secrets 확인하세요.")

    quoted_password = urllib.parse.quote_plus(str(password))
    return f"mssql+pymssql://{username}:{quoted_password}@{server}:{port}/{database}"


@st.cache_resource(show_spinner=False)
def _get_engine() -> Engine:
    db_url = _build_sqlalchemy_url()
    return create_engine(
        db_url,
        pool_size=5,
        max_overflow=0,
        pool_recycle=300,
        pool_pre_ping=True,
        pool_timeout=30,
        connect_args={"login_timeout": 30, "timeout": 30},
    )


def run_query(query: str, params=None, fetch: bool = False):
    """
    params는 dict로 넘기면 됨.
    fetch=True면 DataFrame 반환.
    """
    try:
        engine = _get_engine()
        stmt = text(query)
        with engine.begin() as db:
            if fetch:
                res = db.execute(stmt, params or {})
                return pd.DataFrame(res.fetchall(), columns=res.keys())
            db.execute(stmt, params or {})
        st.cache_data.clear()
        return None
    except Exception as e:
        st.error(f"❌ DB 에러: {e}")
        return None


def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


# ─────────────────────────────────────────────
# DB init (MS SQL)
# ─────────────────────────────────────────────
def init_db():
    """
    앱 시작 시 1회 호출 추천.
    security.py가 기대하는 테이블을 전부 생성/보정한다.
    """
    engine = _get_engine()
    with engine.begin() as s:
        s.execute(text("SELECT 1"))

        # system_config  (예약어: [key], [value])
        s.execute(text("""
            IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='system_config' AND xtype='U')
            CREATE TABLE system_config (
                [key] NVARCHAR(50) PRIMARY KEY,
                [value] NVARCHAR(MAX)
            )
        """))
        s.execute(text("""
            IF NOT EXISTS (SELECT 1 FROM system_config WHERE [key] = 'status')
            INSERT INTO system_config ([key], [value]) VALUES ('status', 'NORMAL')
        """))

        # approved_users
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

        # projects
        s.execute(text("""
            IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='projects' AND xtype='U')
            CREATE TABLE projects (
                id INT IDENTITY(1,1) PRIMARY KEY,
                name NVARCHAR(200) NOT NULL UNIQUE,
                created_at DATETIME DEFAULT GETDATE()
            )
        """))

        # members
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

        # budget_entries (extra_label 포함)
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
        s.execute(text("""
            IF COL_LENGTH('budget_entries', 'extra_label') IS NULL
            ALTER TABLE budget_entries ADD extra_label NVARCHAR(100)
        """))

        # expenses
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

        # reset_logs
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

        # receipt_images
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

        # accounts
        s.execute(text("""
            IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='accounts' AND xtype='U')
            CREATE TABLE accounts (
                id INT IDENTITY(1,1) PRIMARY KEY,
                code NVARCHAR(50) UNIQUE NOT NULL,
                name NVARCHAR(100) NOT NULL,
                type NVARCHAR(50) NOT NULL
            )
        """))

        # journal_entries
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

        # journal_lines
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

        # audit_logs
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

    # ── 계정코드 seed (없으면 넣기)
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
            {"code": code, "name": name, "type": acc_type},
        )

    # ── 총무 계정 부트스트랩 (APPROVED + 권한 세팅)
    admin_sid, admin_name, admin_password = get_admin_bootstrap()
    admin_pw_hash = _hash_password(admin_password) if admin_password else None
    admin_permissions = json.dumps([
        "can_view", "can_edit", "can_manage_members",
        "can_export", "can_archive", "can_delete_project", "can_upload_receipt"
    ])

    run_query("""
        IF EXISTS (SELECT 1 FROM approved_users WHERE student_id = :sid)
            UPDATE approved_users
            SET name = :name,
                role = 'treasurer',
                status = 'APPROVED',
                password_hash = :pw,
                permissions = :perm
            WHERE student_id = :sid
        ELSE
            INSERT INTO approved_users (student_id, name, role, status, password_hash, permissions)
            VALUES (:sid, :name, 'treasurer', 'APPROVED', :pw, :perm)
    """, {"sid": admin_sid, "name": admin_name, "pw": admin_pw_hash, "perm": admin_permissions})


def get_all_data(table_name: str) -> pd.DataFrame:
    allowed = {"projects", "members", "budget_entries", "expenses", "approved_users"}
    if table_name not in allowed:
        return pd.DataFrame()
    return run_query(f"SELECT * FROM {table_name}", fetch=True)


def get_ledger(project_id: int) -> pd.DataFrame:
    query = """
        SELECT entry_date AS transaction_date, created_at AS recorded_at, '수입' AS type,
               CASE source_type
                    WHEN 'student_dues' THEN CONCAT(contributor_name, ' 회비')
                    ELSE CONCAT(ISNULL(contributor_name, ''), ' ', ISNULL(note, ''))
               END AS description,
               amount AS amount
        FROM budget_entries
        WHERE project_id = :pid

        UNION ALL

        SELECT date AS transaction_date, created_at AS recorded_at, '지출' AS type,
               CONCAT(item, ' (', ISNULL(category, '기타'), ')') AS description,
               -amount AS amount
        FROM expenses
        WHERE project_id = :pid

        ORDER BY transaction_date ASC, recorded_at ASC
    """
    return run_query(query, {"pid": project_id}, fetch=True)
