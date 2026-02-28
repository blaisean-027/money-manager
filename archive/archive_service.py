import datetime
import json
import pandas as pd
from typing import Any, Tuple
from sqlalchemy import text
import streamlit as st
from db import run_query, conn

def _table_exists(table: str) -> bool:
    """Azure SQL에서 테이블 존재 확인"""
    df = run_query(
        "SELECT name FROM sys.objects WHERE object_id = OBJECT_ID(:name) AND type = 'U'",
        {"name": table},
        fetch=True
    )
    return df is not None and not df.empty

def _fetch_if_exists(table: str, query: str, params=None) -> list[dict[str, Any]]:
    if not _table_exists(table):
        return []
    df = run_query(query, params, fetch=True)
    if df is not None and not df.empty:
        return df.astype(str).to_dict(orient="records")
    return []

def _ensure_archive_history_table():
    """Azure SQL용 IDENTITY 문법 적용"""
    run_query("""
        IF NOT EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID('archive_history') AND type = 'U')
        CREATE TABLE archive_history (
            id             INT IDENTITY(1,1) PRIMARY KEY,
            project_id     INT NOT NULL,
            project_name   NVARCHAR(MAX),
            archived_by    NVARCHAR(MAX),
            archive_reason NVARCHAR(MAX),
            archived_at    NVARCHAR(MAX),
            filename       NVARCHAR(MAX)
        )
    """)

def archive_project(project_id: int, current_user: dict, archive_reason: str) -> Tuple[str, str]:
    if not archive_reason or not archive_reason.strip():
        raise ValueError("archive_reason is required")

    df_meta = run_query("SELECT * FROM projects WHERE id = :pid", {"pid": project_id}, fetch=True)
    if df_meta is None or df_meta.empty:
        raise ValueError(f"Invalid project_id: {project_id}")

    project_meta_dict = df_meta.astype(str).iloc[0].to_dict()

    journal_entries = _fetch_if_exists("journal_entries", "SELECT * FROM journal_entries WHERE project_id = :pid ORDER BY id", {"pid": project_id})
    journal_entry_ids = [int(row["id"]) for row in journal_entries] if journal_entries else []

    # Azure SQL에서는 IN 구문 사용
    if journal_entry_ids and _table_exists("journal_lines"):
        id_list = ",".join(map(str, journal_entry_ids))
        df_lines = run_query(f"SELECT * FROM journal_lines WHERE journal_entry_id IN ({id_list}) ORDER BY id", fetch=True)
        journal_lines = df_lines.astype(str).to_dict(orient="records") if (df_lines is not None and not df_lines.empty) else []
    else:
        journal_lines = []

    budget_entries = _fetch_if_exists("budget_entries", "SELECT * FROM budget_entries WHERE project_id = :pid ORDER BY id", {"pid": project_id})
    expenses = _fetch_if_exists("expenses", "SELECT * FROM expenses WHERE project_id = :pid ORDER BY id", {"pid": project_id})
    members = _fetch_if_exists("members", "SELECT * FROM members WHERE project_id = :pid ORDER BY id", {"pid": project_id})

    archived_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_filename = f"archive_project_{project_id}_{timestamp}.json"

    payload = {
        "archived_at": archived_at,
        "archived_by": current_user.get("name", "unknown"),
        "archive_reason": archive_reason,
        "project_id": project_id,
        "project_meta": project_meta_dict,
        "data": {
            "journal_entries": journal_entries,
            "journal_lines": journal_lines,
            "budget_entries": budget_entries,
            "expenses": expenses,
            "members": members,
            "audit_logs": [],
        },
    }
    return archive_filename, json.dumps(payload, ensure_ascii=False, indent=2)

def delete_archived_project_data(project_id: int, archived_by: str = "unknown", archive_reason: str = "", filename: str = "", delete_project: bool = False):
    _ensure_archive_history_table()
    with conn.session as s:
        try:
            res = s.execute(text("SELECT name FROM projects WHERE id = :pid"), {"pid": project_id}).fetchone()
            project_name = res[0] if res else "unknown"

            s.execute(text("""
                INSERT INTO archive_history (project_id, project_name, archived_by, archive_reason, archived_at, filename)
                VALUES (:pid, :name, :by, :reason, :at, :fname)
            """), {"pid": project_id, "name": project_name, "by": archived_by, "reason": archive_reason, "at": datetime.datetime.now(datetime.timezone.utc).isoformat(), "fname": filename})

            if _table_exists("journal_entries"):
                res_ids = s.execute(text("SELECT id FROM journal_entries WHERE project_id = :pid"), {"pid": project_id}).fetchall()
                entry_ids = [str(r[0]) for r in res_ids]
                if entry_ids and _table_exists("journal_lines"):
                    id_list = ",".join(entry_ids)
                    s.execute(text(f"DELETE FROM journal_lines WHERE journal_entry_id IN ({id_list})"))
                s.execute(text("DELETE FROM journal_entries WHERE project_id = :pid"), {"pid": project_id})

            for table in ("budget_entries", "expenses", "members"):
                if _table_exists(table):
                    s.execute(text(f"DELETE FROM {table} WHERE project_id = :pid"), {"pid": project_id})

            if delete_project:
                s.execute(text("DELETE FROM projects WHERE id = :pid"), {"pid": project_id})
            s.commit()
        except Exception as e:
            s.rollback()
            st.error(f"데이터 삭제 중 오류 발생: {e}")
            raise e
