# tabs/tab_budget.py
import datetime
import pandas as pd
import streamlit as st

from audit import log_action
from db import run_query


INCOME_TYPE_LABELS = {
    "school_budget": "학교/학과 지원금",
    "reserve_fund": "예비비/이월금",
}


def _to_int_amount(value) -> int:
    try:
        return int(value)
    except Exception:
        return 0


def render_budget_tab(current_project_id: int):
    """
    TAB1: 예산 조성 (수입)
    - 학교/학과 지원금 + 예비비/이월금은 프로젝트 생성과 분리하여 여기서 입력
    - 학생회비 입력 시 이름/학번/입금일을 기록
    """
    st.subheader("1️⃣ 예산/예비비 입력")

    col_budget_form, col_budget_table = st.columns([1, 2])

    with col_budget_form:
        with st.form("add_budget_entry"):
            income_date = st.date_input("입금일", datetime.date.today(), key="budget_date")
            income_type = st.selectbox(
                "수입 구분",
                ["school_budget", "reserve_fund"],
                format_func=lambda x: INCOME_TYPE_LABELS.get(x, x),
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
                run_query(
                    """
                    INSERT INTO budget_entries
                    (project_id, entry_date, source_type, contributor_name, amount, note)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        current_project_id,
                        income_date.strftime("%Y-%m-%d"),
                        income_type,
                        contributor_name.strip(),
                        _to_int_amount(amount),
                        note.strip(),
                    ),
                )
                log_action(
                    "예산 수입 등록",
                    f"{income_date} / {INCOME_TYPE_LABELS.get(income_type)} / {contributor_name} / {int(amount):,}원",
                )
                st.success("예산/예비비 항목을 등록했어요.")
                st.rerun()

    with col_budget_table:
        budget_rows = run_query(
            """
            SELECT entry_date, source_type, contributor_name, amount, note
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
                columns=["입금일", "구분", "입금자", "금액", "비고"],
            )
            df_budget["구분"] = df_budget["구분"].map(lambda x: INCOME_TYPE_LABELS.get(x, x))
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
                run_query(
                    """
                    INSERT INTO members (project_id, name, student_id, deposit_amount, paid_date, note)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        current_project_id,
                        m_name.strip(),
                        m_sid.strip(),
                        _to_int_amount(m_amt),
                        paid_date.strftime("%Y-%m-%d"),
                        m_note.strip(),
                    ),
                )
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
        "SELECT COALESCE(SUM(amount), 0) FROM budget_entries WHERE project_id = ? AND source_type = 'reserve_fund'",
        (current_project_id,),
        fetch=True,
    )
    school_budget_total = int(school_budget_total_row[0][0]) if school_budget_total_row else 0
    reserve_total = int(reserve_total_row[0][0]) if reserve_total_row else 0

    st.markdown("### 📊 총 수입 요약")
    total_budget = school_budget_total + reserve_total + total_student_dues

    s1, s2, s3, s4 = st.columns(4)
    s1.metric("학교/학과 지원금", f"{school_budget_total:,.0f}원")
    s2.metric("예비비/이월금", f"{reserve_total:,.0f}원")
    s3.metric("학생회비 합계", f"{total_student_dues:,.0f}원")
    s4.metric("총 예산", f"{total_budget:,.0f}원")

    return total_budget, total_student_dues, df_members
