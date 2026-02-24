# db.py
import hashlib
import sqlite3

import pandas as pd
import streamlit as st

from config import DB_FILE, get_admin_bootstrap


def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def init_db():
    """모든 테이블 생성, 승인 시스템 구축 및 마이그레이션."""
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("PRAGMA foreign_keys = ON;")
        c = conn.cursor()

        c.execute(
            """
            CREATE TABLE IF NOT EXISTS system_config (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """
        )
        c.execute(
            "INSERT OR IGNORE INTO system_config (key, value) VALUES ('status', 'NORMAL')"
        )

        c.execute(
            """
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
        """
        )

        c.execute(
            """
            CREATE TABLE IF NOT EXISTS approved_users (
                student_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                role TEXT DEFAULT 'user',
                status TEXT DEFAULT 'PENDING',
                password_hash TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """
        )

        c.execute(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """
        )

        c.execute(
            """
            CREATE TABLE IF NOT EXISTS members (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER,
                name TEXT NOT NULL,
                student_id TEXT,
                deposit_amount INTEGER DEFAULT 0,
                paid_date TEXT,
                note TEXT,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
                UNIQUE(project_id, name, student_id, paid_date)
            )
        """
        )

        c.execute(
            """
            CREATE TABLE IF NOT EXISTS budget_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER,
                entry_date TEXT,
                source_type TEXT,
                contributor_name TEXT,
                amount INTEGER,
                note TEXT,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
            )
        """
        )

        c.execute(
            """
            CREATE TABLE IF NOT EXISTS expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER,
                date TEXT,
                item TEXT,
                amount INTEGER,
                category TEXT,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
            )
        """
        )

        migrations = [
            ("audit_logs", "ip_address", "TEXT"),
            ("audit_logs", "device_info", "TEXT"),
            ("audit_logs", "operator_name", "TEXT"),
            ("approved_users", "status", "TEXT DEFAULT 'PENDING'"),
            ("approved_users", "password_hash", "TEXT"),
            ("members", "note", "TEXT"),
            ("members", "student_id", "TEXT"),
            ("members", "paid_date", "TEXT"),
            ("projects", "school_budget", "INTEGER DEFAULT 0"),
            ("projects", "carry_over_funds", "INTEGER DEFAULT 0"),
        ]

        for table, col, col_type in migrations:
            try:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")
            except Exception:
                pass

        admin_sid, admin_name, admin_password = get_admin_bootstrap()
        if admin_sid == "admin" and admin_name == "안효현":
            admin_sid = "202203166"

        admin_password_hash = _hash_password(admin_password) if admin_password else None

        c.execute(
            """
            INSERT OR IGNORE INTO approved_users (student_id, name, role, status, password_hash)
            VALUES (?, ?, 'treasurer', 'APPROVED', ?)
        """,
            (admin_sid, admin_name, admin_password_hash),
        )

        if admin_password_hash:
            c.execute(
                """
                UPDATE approved_users
                SET name = ?, role = 'treasurer', status = 'APPROVED', password_hash = ?
                WHERE student_id = ?
            """,
                (admin_name, admin_password_hash, admin_sid),
            )

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


def get_all_data(table_name: str) -> pd.DataFrame:
    """레거시 탭 호환용: 테이블 전체를 DataFrame으로 반환."""
    allowed = {
        "projects",
        "members",
        "budget_entries",
        "expenses",
        "approved_users",
        "audit_logs",
    }
    if table_name not in allowed:
        return pd.DataFrame()

    with sqlite3.connect(DB_FILE) as conn:
        try:
            return pd.read_sql_query(f"SELECT * FROM {table_name}", conn)
        except Exception:
            return pd.DataFrame()

