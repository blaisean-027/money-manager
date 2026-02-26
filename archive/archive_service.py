# archive/archive_service.py

import datetime
import json
import sqlite3
from typing import Any, Tuple

from config import DB_FILE


def _fetch_rows_as_dicts(conn: sqlite3.Connection, query: str, params=()) -> list[dict[str, Any]]:
    cur = conn.execute(query, params)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return bool(row)


def _fetch_if_exists(
    conn: sqlite3.Connection, table: str, query: str, params=()
) -> list[dict[str, Any]]:
    """테이블이 존재할 때만 fetch, 없으면 빈 리스트 반환."""
    if not _table_exists(conn, table):
        return []
    return _fetch_rows_as_dicts(conn, query, params)


def _ensure_archive_history_table(conn: sqlite3.Connection):
    """운영 DB에 아카이브 이력 테이블 보장 (JSON 분실 시에도 추적 가능)."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS archive_history (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
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

    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row

        project_meta = conn.execute(
            "SELECT * FROM projects WHERE id = ?",
            (project_id,),
        ).fetchone()

        if not project_meta:
            raise ValueError(f"Invalid project_id: {project_id}")

        project_meta_dict = dict(project_meta)

        # journal_entries / journal_lines (없을 수도 있음)
        journal_entries = _fetch_if_exists(
            conn, "journal_entries",
            "SELECT * FROM journal_entries WHERE project_id = ? ORDER BY id",
            (project_id,),
        )
        journal_entry_ids = [row["id"] for row in journal_entries]

        if journal_entry_ids and _table_exists(conn, "journal_lines"):
            placeholders = ",".join("?" for _ in journal_entry_ids)
            journal_lines = _fetch_rows_as_dicts(
                conn,
                f"SELECT * FROM journal_lines WHERE journal_entry_id IN ({placeholders}) ORDER BY id",
                tuple(journal_entry_ids),
            )
        else:
            journal_lines = []

        budget_entries = _fetch_if_exists(
            conn, "budget_entries",
            "SELECT * FROM budget_entries WHERE project_id = ? ORDER BY id",
            (project_id,),
        )

        expenses = _fetch_if_exists(
            conn, "expenses",
            "SELECT * FROM expenses WHERE project_id = ? ORDER BY id",
            (project_id,),
        )

        members = _fetch_if_exists(
            conn, "members",
            "SELECT * FROM members WHERE project_id = ? ORDER BY id",
            (project_id,),
        )

        # ✅ audit_logs는 project_id 컬럼 없는 글로벌 로그 → 아카이브 제외
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
    존재하지 않는 테이블은 자동으로 건너뜀.
    archive_history 테이블에 삭제 이력을 기록한다.
    """
    with sqlite3.connect(DB_FILE) as conn:
        conn.isolation_level = None
        conn.execute("PRAGMA foreign_keys = ON;")

        try:
            conn.execute("BEGIN;")
            cur = conn.cursor()

            # ── archive_history 기록 (JSON 분실 대비) ─────────────────────
            _ensure_archive_history_table(conn)
            row = cur.execute(
                "SELECT name FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
            project_name = row[0] if row else "unknown"

            cur.execute(
                """
                INSERT INTO archive_history
                    (project_id, project_name, archived_by, archive_reason, archived_at, filename)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    project_name,
                    archived_by,
                    archive_reason,
                    datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    filename,
                ),
            )

            # ── journal_lines → journal_entries (FK 순서, 테이블 존재 체크) ──
            if _table_exists(conn, "journal_entries"):
                cur.execute(
                    "SELECT id FROM journal_entries WHERE project_id = ?", (project_id,)
                )
                entry_ids = [r[0] for r in cur.fetchall()]

                if entry_ids and _table_exists(conn, "journal_lines"):
                    placeholders = ",".join("?" for _ in entry_ids)
                    cur.execute(
                        f"DELETE FROM journal_lines WHERE journal_entry_id IN ({placeholders})",
                        tuple(entry_ids),
                    )
                cur.execute("DELETE FROM journal_entries WHERE project_id = ?", (project_id,))

            # ✅ audit_logs 제외 (project_id 컬럼 없는 글로벌 로그)
            for table in ("budget_entries", "expenses", "members"):
                if _table_exists(conn, table):
                    cur.execute(f"DELETE FROM {table} WHERE project_id = ?", (project_id,))

            # ── 프로젝트 행 삭제 (선택) ──────────────────────────────────
            if delete_project:
                cur.execute("DELETE FROM projects WHERE id = ?", (project_id,))

            conn.execute("COMMIT;")

        except Exception as e:
            conn.execute("ROLLBACK;")
            raise e

