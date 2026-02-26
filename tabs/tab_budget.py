# tabs/tab_budget.py
import datetime
import sqlite3
import pandas as pd
import streamlit as st

from audit import log_action
from config import DB_FILE
from db import run_query
from accounting.service import record_income_entry


INCOME_TYPE_LABELS = {
    "school_budget": "학교/학과 지원금",
    "reserve_fund": "예비비/이월금(외부 유입)",
    # ✅ 라벨을 '과잠' 고정이 아니라 회수/정산 전반으로 넓힘
    "reserve_recovery": "회수/정산(예비비 복구 등)",
}


def _to_int_amount(value) -> int:
    try:
        return int(value)
    except Exception:
        return 0


def _ensure_budget_entries_extra_label_column():
    """
    budget_entries 테이블에 extra_label 컬럼이 없으면 자동 추가.
    (사용자 입장: 따로 마이그레이션 안 해도 그냥 기능이 켜짐)
    """
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("PRAGMA foreign_keys = ON;")
        cols = conn.execute("PRAGMA table_info(budget_entries)").fetchall()
        col_names = {c[1] for c in cols}  # (cid, name, type, notnull, dflt_value, pk)

        if "extra_label" not in col_names:
            conn.execute("ALTER TABLE budget_entries ADD COLUMN extra_label TEXT DEFAULT ''")
            conn.commit()


def _compose_type_label(source_type: str, extra_label: str) -> str:
    base = INCOME_TYPE_LABELS.get(source_type, source_type)
    extra = (extra_label or "").strip()
    if not extra:
        return base
    return f"{base} - {extra}"


def render_budget_tab(current_project_id: int):
    # ✅ 스키마 자동 보정
    _ensure_budget_entries_extra_label_column()

    st.subheader("1️⃣ 예산/예비비 입력")

    col_budget_form, col_budget_table = st.columns([1, 2])

    with col_budget_form:
        with st.form("add_budget_entry"):
            income_date = st.date_input("입금일", datetime.date.today(), key="budget_date")

            income_type = st.selectbox(
                "수입 구분",
                ["school_budget", "reserve_fund", "reserve_recovery"],
                format_func=lambda x: INCOME_TYPE_LABELS.get(x, x),
            )

            # ✅ +알파 자유 입력
            extra_label = st.text_input(
                "추가 항목 (+알파, 선택)",
                placeholder="예: 24학번 홍길동 과잠비 / MT 회수 / 행사 후원금 등",
            )

            contributor_name = st.text_input("입금자/담당자 이름")
            amount = st.number_input("금액", min_value=0, step=1000)
            note = st.text_input("비고 (선택)")
            submit_budget = st.form_submit_button("예산 항목 등록")

        if submit_budget:
            if not contributor_name.strip():
                st.warning("입금자/담당자 이름을 입력해주세요.")
            elif amount <= 0:
                st.warning("금액은 0원보다 커야 합니다.")
            else:
                tx_date = income_date.strftime("%Y-%m-%d")
                amount_i = _to_int_amount(amount)

                run_query(
                    """
                    INSERT INTO budget_entries
                    (project_id, entry_date, source_type, contributor_name, amount, note, extra_label)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        current_project_id,
                        tx_date,
                        income_type,
                        contributor_name.strip(),
                        amount_i,
                        note.strip(),
                        extra_label.strip(),
                    ),
                )

                with sqlite3.connect(DB_FILE) as conn:
                    conn.execute("PRAGMA foreign_keys = ON;")
                    record_income_entry(
                        conn,
                        project_id=current_project_id,
                        tx_date=tx_date,
                        source_type=income_type,
                        actor_name=contributor_name.strip(),
                        amount=amount_i,
                        note=note.strip(),
                        extra_label=extra_label.strip(),  # ✅ 회계 분개에도 반영
                    )
                    conn.commit()

                pretty_type = _compose_type_label(income_type, extra_label)
                log_action(
                    "예산 수입 등록",
                    f"{income_date} / {pretty_type} / {contributor_name} / {int(amount):,}원",
                )
                st.success("예산/예비비 항목을 등록했어요.")
                st.rerun()

    with col_budget_table:
        budget_rows = run_query(
            """
            SELECT entry_date, source_type, contributor_name, amount, note, COALESCE(extra_label,'')
            FROM budget_entries
            WHERE project_id = ?
            ORDER BY entry_date DESC, id DESC
            """,
            (current_project_id,),
            fetch=True,
        )

        if budget_rows:
            df_budget = pd.DataFrame(
                budget_rows,
                columns=["입금일", "구분", "입금자", "금액", "비고", "추가항목"],
            )

            # ✅ "구분"을 기본라벨 + +알파로 표시(수기 장부 느낌)
            df_budget["구분"] = df_budget.apply(
                lambda r: _compose_type_label(str(r["구분"]), str(r["추가항목"])),
                axis=1,
            )

            # "추가항목" 컬럼은 굳이 따로 보여줄 필요 없으면 숨김
            df_budget = df_budget.drop(columns=["추가항목"])

            st.dataframe(df_budget, use_container_width=True, hide_index=True)
        else:
            df_budget = pd.DataFrame(columns=["입금일", "구분", "입금자", "금액", "비고"])
            st.info("아직 등록된 예산/예비비가 없습니다.")

    st.divider()
    st.subheader("2️⃣ 학생회비 납부 기록")

    col_member_form, col_member_table = st.columns([1, 2])

    with col_member_form:
        with st.form("manual_member_payment"):
            paid_date = st.date_input("납부일", datetime.date.today(), key="member_paid_date")
            m_name = st.text_input("이름")
            m_sid = st.text_input("학번 (선택)")
            m_amt = st.number_input("납부액", min_value=0, step=1000)
            m_note = st.text_input("비고")
            submit_member = st.form_submit_button("학생회비 등록")

        if submit_member:
            if not m_name.strip():
                st.warning("이름을 입력해주세요.")
            elif m_amt <= 0:
                st.warning("납부액은 0원보다 커야 합니다.")
            else:
                tx_date = paid_date.strftime("%Y-%m-%d")
                amount_i = _to_int_amount(m_amt)
                run_query(
                    """
                    INSERT INTO members (project_id, name, student_id, deposit_amount, paid_date, note)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        current_project_id,
                        m_name.strip(),
                        m_sid.strip(),
                        amount_i,
                        tx_date,
                        m_note.strip(),
                    ),
                )
                with sqlite3.connect(DB_FILE) as conn:
                    conn.execute("PRAGMA foreign_keys = ON;")
                    record_income_entry(
                        conn,
                        project_id=current_project_id,
                        tx_date=tx_date,
                        source_type="student_dues",
                        actor_name=m_name.strip(),
                        amount=amount_i,
                        note=m_note.strip(),
                        extra_label="",  # 학생회비는 보통 추가항목 필요 없어서 빈 값
                    )
                    conn.commit()

                log_action(
                    "학생회비 등록",
                    f"{paid_date} / {m_name}({m_sid}) / {int(m_amt):,}원",
                )
                st.success("학생회비를 등록했어요.")
                st.rerun()

    with col_member_table:
        members_data = run_query(
            """
            SELECT paid_date, name, student_id, deposit_amount, note
            FROM members
            WHERE project_id = ?
            ORDER BY paid_date DESC, id DESC
            """,
            (current_project_id,),
            fetch=True,
        )
        if members_data:
            df_members = pd.DataFrame(
                members_data, columns=["납부일", "이름", "학번", "납부액", "비고"]
            )
            st.dataframe(df_members, use_container_width=True, hide_index=True)
            total_student_dues = int(df_members["납부액"].sum())
        else:
            st.info("아직 납부자가 없습니다.")
            df_members = pd.DataFrame(columns=["납부일", "이름", "학번", "납부액", "비고"])
            total_student_dues = 0

    school_budget_total_row = run_query(
        "SELECT COALESCE(SUM(amount), 0) FROM budget_entries WHERE project_id = ? AND source_type = 'school_budget'",
        (current_project_id,),
        fetch=True,
    )
    reserve_total_row = run_query(
        "SELECT COALESCE(SUM(amount), 0) FROM budget_entries WHERE project_id = ? AND source_type IN ('reserve_fund','reserve_recovery')",
        (current_project_id,),
        fetch=True,
    )
    school_budget_total = int(school_budget_total_row[0][0]) if school_budget_total_row else 0
    reserve_total = int(reserve_total_row[0][0]) if reserve_total_row else 0

    st.markdown("### 📊 총 수입 요약")
    total_budget = school_budget_total + reserve_total + total_student_dues

    s1, s2, s3, s4 = st.columns(4)
    s1.metric("학교/학과 지원금", f"{school_budget_total:,.0f}원")
    s2.metric("예비비/회수 합계", f"{reserve_total:,.0f}원")
    s3.metric("학생회비 합계", f"{total_student_dues:,.0f}원")
    s4.metric("총 예산", f"{total_budget:,.0f}원")

    return total_budget, total_student_dues, df_members
