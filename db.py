import hashlib
import json
import sqlite3

import pandas as pd
import streamlit as st

from config import DB_FILE, get_admin_bootstrap


def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def init_db():
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("PRAGMA foreign_keys = ON;")
        c = conn.cursor()

        c.execute("""
            CREATE TABLE IF NOT EXISTS system_config (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        c.execute("INSERT OR IGNORE INTO system_config (key, value) VALUES ('status', 'NORMAL')")

        c.execute("""
            CREATE TABLE IF NOT EXISTS audit_logs (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp     DATETIME DEFAULT CURRENT_TIMESTAMP,
                action        TEXT,
                details       TEXT,
                user_mode     TEXT,
                ip_address    TEXT,
                device_info   TEXT,
                operator_name TEXT
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS approved_users (
                student_id           TEXT PRIMARY KEY,
                name                 TEXT NOT NULL,
                role                 TEXT DEFAULT 'member',
                status               TEXT DEFAULT 'PENDING',
                password_hash        TEXT,
                permissions          TEXT,
                security_question    TEXT,
                security_answer_hash TEXT,
                created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS projects (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                name       TEXT NOT NULL UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS members (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id     INTEGER,
                name           TEXT NOT NULL,
                student_id     TEXT,
                deposit_amount INTEGER DEFAULT 0,
                paid_date      TEXT,
                note           TEXT,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
                UNIQUE(project_id, name, student_id, paid_date)
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS budget_entries (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id       INTEGER,
                entry_date       TEXT,
                source_type      TEXT,
                contributor_name TEXT,
                amount           INTEGER,
                note             TEXT,
                created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS expenses (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER,
                date       TEXT,
                item       TEXT,
                amount     INTEGER,
                category   TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS reset_logs (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id TEXT,
                name       TEXT,
                reset_by   TEXT DEFAULT 'self',
                reset_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_read    INTEGER DEFAULT 0
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS receipt_images (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id   INTEGER NOT NULL,
                expense_id   INTEGER,
                filename     TEXT NOT NULL,
                filepath     TEXT NOT NULL,
                description  TEXT,
                uploaded_by  TEXT,
                uploaded_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY(expense_id) REFERENCES expenses(id) ON DELETE SET NULL
            )
        """)

        migrations = [
            ("audit_logs",     "ip_address",           "TEXT"),
            ("audit_logs",     "device_info",           "TEXT"),
            ("audit_logs",     "operator_name",         "TEXT"),
            ("approved_users", "status",                "TEXT DEFAULT 'PENDING'"),
            ("approved_users", "password_hash",         "TEXT"),
            ("approved_users", "permissions",           "TEXT"),
            ("approved_users", "security_question",     "TEXT"),
            ("approved_users", "security_answer_hash",  "TEXT"),
            ("members",        "note",                  "TEXT"),
            ("members",        "student_id",            "TEXT"),
            ("members",        "paid_date",             "TEXT"),
            ("projects",       "school_budget",         "INTEGER DEFAULT 0"),
            ("projects",       "carry_over_funds",      "INTEGER DEFAULT 0"),
            ("expenses",       "receipt_image_id",      "INTEGER"),
            ("budget_entries", "created_at",            "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
            ("expenses",       "created_at",            "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
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
        admin_permissions = json.dumps([
            "can_view", "can_edit", "can_manage_members",
            "can_export", "can_archive", "can_delete_project",
            "can_upload_receipt",
        ])

        c.execute("""
            INSERT OR IGNORE INTO approved_users
                (student_id, name, role, status, password_hash, permissions)
            VALUES (?, ?, 'treasurer', 'APPROVED', ?, ?)
        """, (admin_sid, admin_name, admin_password_hash, admin_permissions))

        if admin_password_hash:
            c.execute("""
                UPDATE approved_users
                SET name=?, role='treasurer', status='APPROVED',
                    password_hash=?, permissions=?
                WHERE student_id=?
            """, (admin_name, admin_password_hash, admin_permissions, admin_sid))

        conn.commit()


def run_query(query: str, params=(), fetch: bool = False):
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
    allowed = {
        "projects", "members", "budget_entries",
        "expenses", "approved_users", "audit_logs",
    }
    if table_name not in allowed:
        return pd.DataFrame()
    with sqlite3.connect(DB_FILE) as conn:
        try:
            return pd.read_sql_query(f"SELECT * FROM {table_name}", conn)
        except Exception:
            return pd.DataFrame()


def get_ledger(project_id: int) -> pd.DataFrame:
    """수입+지출 통합 가계부 (실제 거래일 기준 정렬)"""
    with sqlite3.connect(DB_FILE) as conn:
        query = f"""
            SELECT
                entry_date   AS transaction_date,
                created_at   AS recorded_at,
                '수입'       AS type,
                CASE source_type
                    WHEN 'student_due' THEN contributor_name || ' 회비'
                    ELSE COALESCE(contributor_name, '') || ' ' || COALESCE(note, '')
                END          AS description,
                amount       AS amount
            FROM budget_entries
            WHERE project_id = {project_id}

            UNION ALL

            SELECT
                date         AS transaction_date,
                created_at   AS recorded_at,
                '지출'       AS type,
                item || ' (' || COALESCE(category, '기타') || ')' AS description,
                -amount      AS amount
            FROM expenses
            WHERE project_id = {project_id}

            ORDER BY transaction_date ASC, recorded_at ASC
        """
        try:
            return pd.read_sql_query(query, conn)
        except Exception:
            return pd.DataFrame(columns=[
                "transaction_date", "recorded_at", "type", "description", "amount"
            ])

