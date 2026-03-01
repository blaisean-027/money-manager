"""
Database access and Azure SQL connection helpers.
Streamlit Cloud + Azure SQL (pymssql 전용 안정 버전)
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
# 1️⃣ DB URL 생성 (pymssql ONLY)
# ─────────────────────────────────────────────

def _secret_get(*keys, default=None):
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
    # 1) 직접 URL이 있으면 최우선 사용
    try:
        if "connections" in st.secrets and "sql" in st.secrets["connections"]:
            cfg = st.secrets["connections"]["sql"]
            if "url" in cfg and cfg["url"]:
                return cfg["url"]
    except Exception:
        pass

    # 2) 개별 값으로 조합 (fallback)
    server = _secret_get("AZURE_SQL_SERVER")
    database = _secret_get("AZURE_SQL_DATABASE")
    username = _secret_get("AZURE_SQL_USER")
    password = _secret_get("AZURE_SQL_PASSWORD")
    port = _secret_get("AZURE_SQL_PORT", default="1433")

    if not all([server, database, username, password]):
        raise RuntimeError("DB 접속 정보가 없습니다. Streamlit Secrets 확인하세요.")

    quoted_password = urllib.parse.quote_plus(password)
    return f"mssql+pymssql://{username}:{quoted_password}@{server}:{port}/{database}"


# ─────────────────────────────────────────────
# 2️⃣ SQLAlchemy Engine
# ─────────────────────────────────────────────

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
        connect_args={
            "login_timeout": 30,
            "timeout": 30
        },
    )


# ─────────────────────────────────────────────
# 3️⃣ 기본 실행 함수
# ─────────────────────────────────────────────

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


# ─────────────────────────────────────────────
# 4️⃣ DB 초기화 (Azure SQL 전용 문법)
# ─────────────────────────────────────────────

def init_db():
    engine = _get_engine()
    with engine.begin() as s:

        s.execute(text("SELECT 1"))

        s.execute(text("""
        IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='projects' AND xtype='U')
        CREATE TABLE projects (
            id INT IDENTITY(1,1) PRIMARY KEY,
            name NVARCHAR(200) NOT NULL UNIQUE,
            created_at DATETIME DEFAULT GETDATE()
        )
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
        IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='budget_entries' AND xtype='U')
        CREATE TABLE budget_entries (
            id INT IDENTITY(1,1) PRIMARY KEY,
            project_id INT REFERENCES projects(id) ON DELETE CASCADE,
            entry_date NVARCHAR(50),
            source_type NVARCHAR(50),
            contributor_name NVARCHAR(100),
            amount INT,
            note NVARCHAR(MAX),
            created_at DATETIME DEFAULT GETDATE()
        )
        """))

    # 관리자 자동 생성
    admin_sid, admin_name, admin_password = get_admin_bootstrap()
    if admin_password:
        pw_hash = hashlib.sha256(admin_password.encode("utf-8")).hexdigest()

        run_query("""
        IF NOT EXISTS (SELECT 1 FROM approved_users WHERE student_id = :sid)
        INSERT INTO approved_users (student_id, name, role, status, password_hash)
        VALUES (:sid, :name, 'treasurer', 'APPROVED', :pw)
        """, {"sid": admin_sid, "name": admin_name, "pw": pw_hash})


# ─────────────────────────────────────────────
# 5️⃣ Ledger 조회
# ─────────────────────────────────────────────

def get_ledger(project_id: int) -> pd.DataFrame:
    query = """
        SELECT entry_date AS transaction_date,
               '수입' AS type,
               amount
        FROM budget_entries
        WHERE project_id = :pid

        UNION ALL

        SELECT date AS transaction_date,
               '지출' AS type,
               -amount AS amount
        FROM expenses
        WHERE project_id = :pid

        ORDER BY transaction_date ASC
    """
    return run_query(query, {"pid": project_id}, fetch=True)
