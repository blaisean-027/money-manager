mport pandas as pd
import streamlit as st
import json
import hashlib
from sqlalchemy import text
from config import get_admin_bootstrap

# ── 1. 수파베이스 트랜잭션 풀러(6543 포트) 전용 설정 ──
# sslmode=require를 통해 보안 연결을 확실히 하고, 
# pool_recycle로 SSL 연결이 갑자기 끊기는 걸 방어해!
conn = st.connection(
    "postgresql", 
    type="sql",
    pool_size=5,         
    max_overflow=0,      
    pool_recycle=300,    
    pool_pre_ping=True,  
    connect_args={"sslmode": "require"} 
)

def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()

# ── 2. DB 초기화 함수 ──
def init_db():
    with conn.session as s:
        s.execute(text("SELECT 1")) # 연결 생존 확인
        
        # 시스템 설정 및 사용자 테이블
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

        # 프로젝트 및 장부 테이블
        s.execute(text("CREATE TABLE IF NOT EXISTS projects (id SERIAL PRIMARY KEY, name TEXT NOT NULL UNIQUE, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"))
        s.execute(text("CREATE TABLE IF NOT EXISTS members (id SERIAL PRIMARY KEY, project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE, name TEXT NOT NULL, student_id TEXT, deposit_amount INTEGER DEFAULT 0, paid_date TEXT, note TEXT)"))
        s.execute(text("CREATE TABLE IF NOT EXISTS budget_entries (id SERIAL PRIMARY KEY, project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE, entry_date TEXT, source_type TEXT, contributor_name TEXT, amount INTEGER, note TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"))
        s.execute(text("CREATE TABLE IF NOT EXISTS expenses (id SERIAL PRIMARY KEY, project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE, date TEXT, item TEXT, amount INTEGER, category TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"))
        s.commit()

    # 관리자 계정 자동 생성
    admin_sid, admin_name, admin_password = get_admin_bootstrap()
    
    # 💡 팁: 실제 본인의 학번과 이름을 넣어두면 편해!
    if admin_name == "안효현":
        admin_sid = "202203166" 

    admin_password_hash = _hash_password(admin_password) if admin_password else None
    admin_permissions = json.dumps(["can_view", "can_edit", "can_manage_members", "can_export", "can_archive", "can_delete_project", "can_upload_receipt"])

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
            return conn.query(query, params=params, ttl=0)
        else:
            with conn.session as s:
                s.execute(text(query), params)
                s.commit()
    except Exception as e:
        st.error(f"❌ DB 에러: {e}")
        return None

def get_all_data(table_name: str) -> pd.DataFrame:
    allowed = {"projects", "members", "budget_entries", "expenses", "approved_users"}
    if table_name not in allowed: return pd.DataFrame()
    return conn.query(f"SELECT * FROM {table_name}", ttl=0)

# ── 4. 🚨 에러 해결의 핵심: 장부 조회 함수 🚨 ──
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
    return conn.query(query, params={"pid": project_id}, ttl=0)
