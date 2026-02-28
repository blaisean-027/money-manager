# archive/archive_service.py

import datetime
import json
import pandas as pd
from typing import Any, Tuple
from sqlalchemy import text

from db import run_query, conn


def _table_exists(table: str) -> bool:
    """PostgreSQL에서 테이블이 존재하는지 확인"""
    df = run_query(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_name=:name",
        {"name": table},
        fetch=True
    )
    return df is not None and not df.empty


def _fetch_if_exists(table: str, query: str, params=None) -> list[dict[str, Any]]:
    """테이블이 존재할 때만 DataFrame으로 fetch 후 dict 리스트로 변환"""
    if not _table_exists(table):
        return []
    
    df = run_query(query, params, fetch=True)
    if df is not None and not df.empty:
        # datetime 객체 등을 JSON 직렬화하기 위해 문자열로 안전하게 캐스팅
        return df.astype(str).to_dict(orient="records")
    return []


def _ensure_archive_history_table():
    """운영 DB에 아카이브 이력 테이블 보장 (PostgreSQL 문법)"""
    run_query("""
        CREATE TABLE IF NOT EXISTS archive_history (
            id             SERIAL PRIMARY KEY,
            project_id     INTEGER NOT NULL,
            project_name   TEXT,
            archived_by    TEXT,
            archive_reason TEXT,
            archived_at    TEXT,
            filename       TEXT
        )
    """)


def archive_project(
    project_id: int,
    current_user: dict,
    archive_reason: str,
) -> Tuple[str, str]:
    """
    프로젝트 전체 데이터를 JSON으로 추출한다. (삭제는 하지 않음)
    반환값: (archive_filename, archive_json_str)
    """
    if not archive_reason or not archive_reason.strip():
        raise ValueError("archive_reason is required")

    df_meta = run_query("SELECT * FROM projects WHERE id = :pid", {"pid": project_id}, fetch=True)
    if df_meta is None or df_meta.empty:
        raise ValueError(f"Invalid project_id: {project_id}")

    project_meta_dict = df_meta.astype(str).iloc[0].to_dict()

    # journal_entries
    journal_entries = _fetch_if_exists(
        "journal_entries",
        "SELECT * FROM journal_entries WHERE project_id = :pid ORDER BY id",
        {"pid": project_id}
    )
    journal_entry_ids = [int(row["id"]) for row in journal_entries] if journal_entries else []

    # PostgreSQL에서는 IN 대신 = ANY(:ids) 배열 검색을 사용하는 것이 안전함
    if journal_entry_ids and _table_exists("journal_lines"):
        df_lines = run_query(
            "SELECT * FROM journal_lines WHERE journal_entry_id = ANY(:ids) ORDER BY id",
            {"ids": journal_entry_ids},
            fetch=True
        )
        journal_lines = df_lines.astype(str).to_dict(orient="records") if (df_lines is not None and not df_lines.empty) else []
    else:
        journal_lines = []

    budget_entries = _fetch_if_exists(
        "budget_entries",
        "SELECT * FROM budget_entries WHERE project_id = :pid ORDER BY id",
        {"pid": project_id}
    )

    expenses = _fetch_if_exists(
        "expenses",
        "SELECT * FROM expenses WHERE project_id = :pid ORDER BY id",
        {"pid": project_id}
    )

    members = _fetch_if_exists(
        "members",
        "SELECT * FROM members WHERE project_id = :pid ORDER BY id",
        {"pid": project_id}
    )

    # audit_logs는 project_id 컬럼 없는 글로벌 로그 → 아카이브 제외
    audit_logs = []

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
            "audit_logs": audit_logs,
        },
    }

    archive_json = json.dumps(payload, ensure_ascii=False, indent=2)
    return archive_filename, archive_json


def delete_archived_project_data(
    project_id: int,
    archived_by: str = "unknown",
    archive_reason: str = "",
    filename: str = "",
    delete_project: bool = False,
):
    """
    실제 데이터 삭제. archive_project() 이후 호출해야 한다.
    """
    _ensure_archive_history_table()

    with conn.session as s:
        try:
            # ── archive_history 기록 (JSON 분실 대비) ─────────────────────
            res = s.execute(text("SELECT name FROM projects WHERE id = :pid"), {"pid": project_id}).fetchone()
            project_name = res[0] if res else "unknown"

            s.execute(
                text("""
                INSERT INTO archive_history
                    (project_id, project_name, archived_by, archive_reason, archived_at, filename)
                VALUES (:pid, :name, :by, :reason, :at, :fname)
                """),
                {
                    "pid": project_id, 
                    "name": project_name, 
                    "by": archived_by,
                    "reason": archive_reason, 
                    "at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "fname": filename
                }
            )

            # ── journal_lines → journal_entries (FK 순서, 테이블 존재 체크) ──
            if _table_exists("journal_entries"):
                res_ids = s.execute(text("SELECT id FROM journal_entries WHERE project_id = :pid"), {"pid": project_id}).fetchall()
                entry_ids = [r[0] for r in res_ids]

                if entry_ids and _table_exists("journal_lines"):
                    s.execute(text("DELETE FROM journal_lines WHERE journal_entry_id = ANY(:ids)"), {"ids": entry_ids})
                s.execute(text("DELETE FROM journal_entries WHERE project_id = :pid"), {"pid": project_id})

            # ✅ 글로벌 로그 제외, 관련 테이블들만 싹 비우기
            for table in ("budget_entries", "expenses", "members"):
                if _table_exists(table):
                    s.execute(text(f"DELETE FROM {table} WHERE project_id = :pid"), {"pid": project_id})

            # ── 프로젝트 행 삭제 (선택) ──────────────────────────────────
            if delete_project:
                s.execute(text("DELETE FROM projects WHERE id = :pid"), {"pid": project_id})

            # 변경사항 최종 확정!
            s.commit()

        except Exception as e:
            # 에러 나면 삭제했던 거 전부 원래대로 되돌림 (안전장치)
            s.rollback()
            st.error(f"데이터 삭제 중 오류 발생: {e}")
            raise e
        
