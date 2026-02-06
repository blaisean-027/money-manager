# db.py
import sqlite3
import streamlit as st
from config import DB_FILE

def init_db():
    """모든 테이블 생성, 승인 시스템 구축 및 마이그레이션."""
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("PRAGMA foreign_keys = ON;")
        c = conn.cursor()

        # 1. 시스템 설정 & 로그 테이블
        c.execute("""
            CREATE TABLE IF NOT EXISTS system_config (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        c.execute("INSERT OR IGNORE INTO system_config (key, value) VALUES ('status', 'NORMAL')")

        c.execute("""
            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                action TEXT,
                details TEXT,
                user_mode TEXT,
                ip_address TEXT,
                device_info TEXT,
                operator_name TEXT
            )
        """)

        # 2. ✅ 승인된 사용자(학번) 테이블 (승인 매커니즘 핵심)
        c.execute("""
            CREATE TABLE IF NOT EXISTS approved_users (
                student_id TEXT PRIMARY KEY,       -- 학번을 고유 키로 사용
                name TEXT NOT NULL,
                role TEXT DEFAULT 'user',          -- user / admin
                status TEXT DEFAULT 'PENDING',     -- PENDING(대기), APPROVED(승인), REJECTED(거절)
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 🛡️ 초기 관리자(안효현) 자동 등록 로직
        # 시스템 잠김 방지를 위해 너의 정보는 미리 'APPROVED' 상태로 넣어둘게.
        c.execute("""
            INSERT OR IGNORE INTO approved_users (student_id, name, role, status) 
            VALUES ('admin', '안효현', 'admin', 'APPROVED')
        """)

        # 3. 프로젝트, 멤버, 지출 테이블
        c.execute("""
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                school_budget INTEGER DEFAULT 0,
                carry_over_funds INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS members (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER,
                name TEXT NOT NULL,
                deposit_amount INTEGER DEFAULT 0,
                note TEXT,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
                UNIQUE(project_id, name)
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER,
                date TEXT,
                item TEXT,
                amount INTEGER,
                category TEXT,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
            )
        """)

        # 4. 마이그레이션 (기존 DB 사용자를 위한 컬럼 추가)
        migrations = [
            ("audit_logs", "ip_address", "TEXT"),
            ("audit_logs", "device_info", "TEXT"),
            ("audit_logs", "operator_name", "TEXT"),
            ("projects", "school_budget", "INTEGER DEFAULT 0"),
            ("projects", "carry_over_funds", "INTEGER DEFAULT 0"),
            ("approved_users", "status", "TEXT DEFAULT 'PENDING'") # status 컬럼 추가
        ]

        for table, col, col_type in migrations:
            try:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")
            except Exception:
                pass # 이미 컬럼이 존재하는 경우 무시

        conn.commit()

def run_query(query: str, params=(), fetch: bool = False):
    """공통 DB 쿼리 함수."""
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("PRAGMA foreign_keys = ON;")
        c = conn.cursor()
        try:
            c.execute(query, params)
            if fetch:
                return c.fetchall()
            conn.commit()
        except sqlite3.Error as e:
            st.error(f"DB 에러: {e}")
            return []