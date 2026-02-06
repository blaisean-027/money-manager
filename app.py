# app.py
import streamlit as st

from config import init_page, init_ai
from db import init_db
from security import check_rubicon_security
from sidebar import render_sidebar

from tabs.tab_budget import render_budget_tab
from tabs.tab_expense import render_expense_tab
from tabs.tab_summary import render_summary_tab


def main():
    init_page()
    model, ai_available = init_ai()
    init_db()

    check_rubicon_security()

    # 로그인 + 사이드바 + 프로젝트 선택
    current_user, selected_project_name, current_project_id = render_sidebar(
        ai_available
    )

    st.title(f"🏫 {selected_project_name} 통합 회계 장부")

    # 일반 사용자에게만 인사 (관리자는 생략해도 됨)
    if current_user.get("role") != "admin":
        st.caption(
            f"👋 안녕하세요, **{current_user.get('name')}** 학우님! 꼼꼼한 기록 부탁드려요."
        )

    tab1, tab2, tab3 = st.tabs(
        ["💰 예산 조성 (수입)", "💸 지출 내역", "📊 최종 결산 및 AI 리포트"]
    )

    with tab1:
        total_budget, total_student_dues, df_members = render_budget_tab(
            current_project_id
        )

    with tab2:
        total_expense, df_expenses = render_expense_tab(current_project_id)

    with tab3:
        render_summary_tab(
            selected_project_name=selected_project_name,
            total_budget=total_budget,
            total_expense=total_expense,
            df_expenses=df_expenses,
            df_members=df_members,
            model=model,
            ai_available=ai_available,
        )


if __name__ == "__main__":
    main()
