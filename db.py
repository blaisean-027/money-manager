iimport os
import json
import hashlib
import urllib.parse

import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from config import get_admin_bootstrap

# ── 1. 연결 설정 (Azure SQL 우선) ──
def _secret_get(*keys, default=None):
    """st.secrets / 환경변수에서 순차 조회"""
    for key in keys:
        try:
            if key in st.secrets:
                return st.secrets[key]
        except Exception:
            pass
        val = os.getenv(key)
        if val:
            return val
    return default

def _build_sqlalchemy_url() -> str:
    # 1) 완성 URL이 있으면 최우선 사용
    direct_url = _secret_get("SQLALCHEMY_DATABASE_URI", "DATABASE_URL", "AZURE_SQL_URL")
    if direct_url:
        return direct_url

    # 2) streamlit [connections.sql] 포맷 사용 시도
    try:
        if "connections" in st.secrets and "sql" in st.secrets["connections"]:
            cfg = st.secrets["connections"]["sql"]
            if "url" in cfg and cfg["url"]:
                return cfg["url"]

            # url 없이 개별 필드(host/user/password/database)가 들어온 경우도 지원
            host = cfg.get("host") or cfg.get("server")
            database = cfg.get("database") or cfg.get("db")
            username = cfg.get("username") or cfg.get("user")
            password = cfg.get("password")
            port = cfg.get("port", 1433)
            dialect = cfg.get("dialect", "mssql")
            driver = cfg.get("driver", "pymssql")

            if all([host, database, username, password]) and dialect == "mssql":
                quoted_password = urllib.parse.quote_plus(str(password))
                return f"mssql+{driver}://{username}:{quoted_password}@{host}:{port}/{database}"
    except Exception:
        pass

    # 3) 개별 값으로 Azure SQL URL 조립
    server = _secret_get("AZURE_SQL_SERVER", "DB_HOST")
    database = _secret_get("AZURE_SQL_DATABASE", "DB_NAME")
    username = _secret_get("AZURE_SQL_USER", "DB_USER")
    password = _secret_get("AZURE_SQL_PASSWORD", "DB_PASSWORD")
    port = _secret_get("AZURE_SQL_PORT", "DB_PORT", default="1433")

    if not all([server, database, username, password]):
        raise RuntimeError(
            "DB 접속 정보가 없습니다. secrets 또는 환경변수에 SQLALCHEMY_DATABASE_URI(권장) "
            "또는 AZURE_SQL_SERVER/AZURE_SQL_DATABASE/AZURE_SQL_USER/AZURE_SQL_PASSWORD를 설정하세요."
        )

    quoted_password = urllib.parse.quote_plus(password)
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
        connect_args={"login_timeout": 30, "timeout": 30} if db_url.startswith("mssql+pymssql") else {},
    )

class _CompatConn:
    """기존 `conn.session` / `conn.query` 호출을 유지하기 위한 호환 래퍼."""

    @property
    def session(self):
        return _get_engine().connect()

    def query(self, query: str, params=None, ttl: int = 30):
        _ = ttl  # streamlit connection API 호환용 (미사용)
        return run_query(query, params=params, fetch=True)


# 과거 코드 호환을 위해 `conn` 심볼 유지
conn = _CompatConn()

def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()

# ── 2. DB 초기화 함수 (Azure T-SQL 문법 적용) ──
def init_db():
    engine = _get_engine()
    with engine.begin() as s:
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
        engine = _get_engine()
        stmt = text(query)
        with engine.begin() as db:
            if fetch:
                result = db.execute(stmt, params or {})
                return pd.DataFrame(result.fetchall(), columns=result.keys())
            db.execute(stmt, params or {})
        st.cache_data.clear()
        return None
    except Exception as e:
        st.error(f"❌ DB 에러: {e}")
        return None

def get_all_data(table_name: str) -> pd.DataFrame:
    allowed = {"projects", "members", "budget_entries", "expenses", "approved_users"}
    if table_name not in allowed:
        return pd.DataFrame()
    return run_query(f"SELECT * FROM {table_name}", fetch=True)

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
    return run_query(query, {"pid": project_id}, fetch=True)
