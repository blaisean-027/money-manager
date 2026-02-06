# tabs/tab_expense.py
import datetime

import pandas as pd
import streamlit as st

from db import run_query
from audit import log_action


def render_expense_tab(current_project_id: int):
    """
    TAB2: 지출 관리 화면.
    반환:
      - total_expense: 총 지출
      - df_expenses: 지출 DataFrame
    """
    col_e1, col_e2 = st.columns([1, 2])

    with col_e1:
        st.subheader("💳 지출 기록")
        with st.form("add_expense"):
            date = st.date_input("날짜", datetime.date.today())
            item = st.text_input("내역 (예: OT 대관료)")
            category = st.selectbox(
                "분류",
                ["식비/간식", "회식비", "장소대관",
                 "물품구매", "홍보비", "교통비", "기타"],
            )
            amount = st.number_input("금액", step=100)
            if st.form_submit_button("지출 등록"):
                run_query(
                    """
                    INSERT INTO expenses
                    (project_id, date, item, amount, category)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (current_project_id, date, item, amount, category),
                )
                log_action(
                    "지출 등록",
                    f"{date} / {item} / {amount}원 / {category}",
                )
                st.rerun()

    with col_e2:
        st.subheader("📋 지출 내역")
        expenses_data = run_query(
            """
            SELECT date, category, item, amount
            FROM expenses
            WHERE project_id = ?
            ORDER BY date DESC
            """,
            (current_project_id,),
            fetch=True,
        )

        if expenses_data:
            df_expenses = pd.DataFrame(
                expenses_data, columns=["날짜", "분류", "내역", "금액"]
            )
            st.dataframe(df_expenses, use_container_width=True, hide_index=True)
            total_expense = df_expenses["금액"].sum()
            st.error(f"💸 총 지출: {total_expense:,.0f}원")
        else:
            df_expenses = pd.DataFrame(
                columns=["날짜", "분류", "내역", "금액"]
            )
            total_expense = 0
            st.info("지출 내역이 없어.")

    return total_expense, df_expenses

