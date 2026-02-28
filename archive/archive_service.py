# archive_service.py (수정된 핵심 함수들)

def _ensure_archive_history_table():
    """운영 DB에 아카이브 이력 테이블 보장 (Azure SQL 문법)"""
    run_query("""
        IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='archive_history' AND xtype='U')
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

def archive_project(project_id: int, current_user: dict, archive_reason: str):
    # ...(앞부분 생략, 기존 코드와 동일)...

    # Azure SQL에서는 ANY(:ids) 대신 IN 구문을 사용하기 위해 ID 리스트를 튜플로 변환
    if journal_entry_ids and _table_exists("journal_lines"):
        # 파이썬 리스트를 SQL IN 구문에 맞게 문자열로 변환 (예: "1, 2, 3")
        id_list_str = ",".join(map(str, journal_entry_ids))
        df_lines = run_query(
            f"SELECT * FROM journal_lines WHERE journal_entry_id IN ({id_list_str}) ORDER BY id",
            fetch=True
        )
        journal_lines = df_lines.astype(str).to_dict(orient="records") if (df_lines is not None and not df_lines.empty) else []
    else:
        journal_lines = []

    # ...(뒷부분 생략, 기존 코드와 동일)...

def delete_archived_project_data(project_id: int, archived_by: str = "unknown", archive_reason: str = "", filename: str = "", delete_project: bool = False):
    _ensure_archive_history_table()
    with conn.session as s:
        try:
            # ...(INSERT archive_history 부분 기존과 동일)...

            # ── journal_lines → journal_entries ──
            if _table_exists("journal_entries"):
                res_ids = s.execute(text("SELECT id FROM journal_entries WHERE project_id = :pid"), {"pid": project_id}).fetchall()
                entry_ids = [str(r[0]) for r in res_ids]

                if entry_ids and _table_exists("journal_lines"):
                    id_list_str = ",".join(entry_ids)
                    s.execute(text(f"DELETE FROM journal_lines WHERE journal_entry_id IN ({id_list_str})"))
                s.execute(text("DELETE FROM journal_entries WHERE project_id = :pid"), {"pid": project_id})

            # ...(나머지 삭제 로직 기존과 동일)...
            s.commit()
        except Exception as e:
            s.rollback()
            raise e
