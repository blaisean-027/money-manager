# tabs/tab_budget.py
import datetime

import pandas as pd
import streamlit as st

from db import run_query
from audit import log_action


def render_budget_tab(current_project_id: int):
    """
    TAB1: 예산 조성 (수입) 화면을 그림.
    반환:
      - total_budget: 총 예산 (지원금 + 이월금 + 학생회비)
      - total_student_dues: 학생회비 총합
      - df_members: 납부 명단 DataFrame (엑셀용)
    """
    # 현재 프로젝트의 고정 예산
    proj_info = run_query(
        "SELECT school_budget, carry_over_funds FROM projects WHERE id = ?",
        (current_project_id,),
        fetch=True,
    )
    current_school_budget = proj_info[0][0] if proj_info else 0
    current_carry_over = proj_info[0][1] if proj_info else 0

    st.subheader("1️⃣ 고정 예산 (Institutional Budget)")
    with st.form("budget_source_form"):
        col_b1, col_b2 = st.columns(2)
        new_school_budget = col_b1.number_input(
            "🏫 학교/학과 지원금",
            value=current_school_budget,
            step=10000,
        )
        new_carry_over = col_b2.number_input(
            "💼 전년도 이월금/예비비",
            value=current_carry_over,
            step=10000,
        )
        if st.form_submit_button("고정 예산 업데이트"):
            run_query(
                "UPDATE projects SET school_budget = ?, carry_over_funds = ? WHERE id = ?",
                (new_school_budget, new_carry_over, current_project_id),
            )
            log_action(
                "예산 수정",
                f"지원금: {new_school_budget}, 이월금: {new_carry_over}로 수정",
            )
            st.success("예산 정보가 수정됐어!")
            st.rerun()

    st.divider()
    st.subheader("2️⃣ 학생회비 납부 (Student Dues)")

    col_m1, col_m2 = st.columns([1, 2])

    # 왼쪽: 업로드/수동 입력
    with col_m1:
        st.caption("엑셀 업로드 또는 수동 입력")
        uploaded_file = st.file_uploader(
            "명단 파일(xlsx/csv)", type=["xlsx", "csv"]
        )
        if uploaded_file:
            try:
                if uploaded_file.name.endswith(".csv"):
                    df_upload = pd.read_csv(uploaded_file)
                else:
                    df_upload = pd.read_excel(uploaded_file)

                # 컬럼명 자동 매핑
                renamed_cols = {}
                for col in df_upload.columns:
                    if any(x in col for x in ["이름", "성명", "Name"]):
                        renamed_cols[col] = "이름"
                    if any(x in col for x in ["금액", "입금", "Amount"]):
                        renamed_cols[col] = "입금액"
                df_upload.rename(columns=renamed_cols, inplace=True)

                if "이름" in df_upload.columns and "입금액" in df_upload.columns:
                    if st.button("일괄 등록"):
                        count = 0
                        for _, row in df_upload.iterrows():
                            try:
                                amt = int(
                                    str(row["입금액"])
                                    .replace(",", "")
                                    .replace("원", "")
                                )
                            except Exception:
                                amt = 0
                            run_query(
                                """
                                INSERT OR IGNORE INTO members
                                (project_id, name, deposit_amount, note)
                                VALUES (?, ?, ?, ?)
                                """,
                                (
                                    current_project_id,
                                    row["이름"],
                                    amt,
                                    "엑셀업로드",
                                ),
                            )
                            count += 1
                        log_action(
                            "멤버 일괄 업로드",
                            f"{count}명 데이터 엑셀로 업로드됨",
                        )
                        st.success("업로드 완료!")
                        st.rerun()
                else:
                    st.error("컬럼명을 확인해줘 (이름, 입금액)")
            except Exception as e:
                st.error(f"에러: {e}")

        with st.expander("수동 추가"):
            with st.form("manual_mem"):
                m_name = st.text_input("이름")
                m_amt = st.number_input("납부액", step=1000)
                if st.form_submit_button("추가"):
                    run_query(
                        """
                        INSERT INTO members (project_id, name, deposit_amount)
                        VALUES (?, ?, ?)
                        """,
                        (current_project_id, m_name, m_amt),
                    )
                    log_action(
                        "멤버 추가",
                        f"이름: {m_name}, 금액: {m_amt}원 추가",
                    )
                    st.rerun()

    # 오른쪽: 명단/합계
    with col_m2:
        members_data = run_query(
            "SELECT id, name, deposit_amount FROM members WHERE project_id = ?",
            (current_project_id,),
            fetch=True,
        )
        if members_data:
            df_members = pd.DataFrame(
                members_data, columns=["ID", "이름", "납부액"]
            )
            st.dataframe(df_members, use_container_width=True, hide_index=True)
            total_student_dues = df_members["납부액"].sum()
        else:
            st.info("아직 납부자가 없어.")
            df_members = pd.DataFrame(columns=["ID", "이름", "납부액"])
            total_student_dues = 0

    total_budget = current_school_budget + current_carry_over + total_student_dues
    st.info(f"💰 **총 예산 합계: {total_budget:,.0f}원**")

    return total_budget, total_student_dues, df_members

