import inspect
import pandas as pd
import streamlit as st
from importlib import import_module

from config import init_page, init_ai
from db import init_db, run_query
from security import check_rubicon_security
from sidebar import render_sidebar

def _resolve_tab_renderer(module_name: str, *candidate_names: str):
    module = import_module(module_name)
    for name in candidate_names:
        fn = getattr(module, name, None)
        if callable(fn):
            return fn
    raise ImportError(f"{module_name}에서 사용할 수 있는 렌더 함수를 찾지 못했습니다: {candidate_names}")

def _call_with_supported_args(fn, **kwargs):
    sig = inspect.signature(fn)
    bound = {k: v for k, v in kwargs.items() if k in sig.parameters}

    # **kwargs 파라미터가 있으면 전부 넘기기
    for param in sig.parameters.values():
        if param.kind == inspect.Parameter.VAR_KEYWORD:
            return fn(**kwargs)

    if not bound and kwargs:
        params = list(sig.parameters.keys())
        if params:
            if len(params) == 1:
                return fn(kwargs.get("current_project_id"))
            if len(params) >= 2:
                return fn(kwargs.get("current_project_id"), kwargs.get("user_role"))

    return fn(**bound)

def _fallback_budget_data(current_project_id: int):
    df_budget = run_query(
        "SELECT COALESCE(SUM(amount), 0) AS total FROM budget_entries WHERE project_id = :pid",
        {"pid": current_project_id}, fetch=True,
    )
    budget_total = int(df_budget.iloc[0]["total"]) if (df_budget is not None and not df_budget.empty) else 0

    df_members_raw = run_query(
        "SELECT paid_date, name, student_id, deposit_amount, note FROM members WHERE project_id = :pid",
        {"pid": current_project_id}, fetch=True,
    )
    if df_members_raw is not None and not df_members_raw.empty:
        df_members = df_members_raw.rename(columns={
            "paid_date": "납부일", "name": "이름", "student_id": "학번",
            "deposit_amount": "납부액", "note": "비고"
        })
    else:
        df_members = pd.DataFrame(columns=["납부일", "이름", "학번", "납부액", "비고"])

    total_student_dues = int(df_members["납부액"].sum()) if not df_members.empty else 0
    return budget_total + total_student_dues, total_student_dues, df_members

def _fallback_expense_data(current_project_id: int):
    df_exp = run_query(
        "SELECT id, date, item, amount, category FROM expenses WHERE project_id = :pid",
        {"pid": current_project_id}, fetch=True,
    )
    if df_exp is not None and not df_exp.empty:
        df = df_exp.rename(columns={"id": "ID", "date": "날짜", "item": "항목", "amount": "금액", "category": "분류"})
        return int(df["금액"].sum()), df
    return 0, pd.DataFrame(columns=["ID", "날짜", "항목", "금액", "분류"])

def _normalize_budget_result(result, current_project_id: int):
    if isinstance(result, tuple) and len(result) == 3:
        return result
    return _fallback_budget_data(current_project_id)

def _normalize_expense_result(result, current_project_id: int):
    if isinstance(result, tuple) and len(result) == 2:
        return result
    return _fallback_expense_data(current_project_id)

render_budget_tab = _resolve_tab_renderer(
    "tabs.tab_budget", "render_budget_tab", "render_budget", "render",
)
render_expense_tab = _resolve_tab_renderer(
    "tabs.tab_expense", "render_expense_tab", "render_expense", "render",
)
render_summary_tab = _resolve_tab_renderer(
    "tabs.tab_summary", "render_summary_tab", "render_summary", "render",
)
render_ledger_tab = _resolve_tab_renderer(
    "tabs.tab_ledger", "render_ledger_tab", "render",
)

def main():
    init_page()
    client, ai_available = init_ai()
    init_db()

    st.session_state["ai_client"] = client if ai_available else None

    check_rubicon_security()

    current_user, selected_project_name, current_project_id = render_sidebar(ai_available)

    check_rubicon_security(current_user)

    st.title(f"🏫 {selected_project_name} 통합 회계 장부")

    if current_user.get("role") not in {"admin", "treasurer"}:
        st.caption(f"👋 안녕하세요, **{current_user.get('name')}** 학우님! 꼼꼼한 기록 부탁드려요.")

    tab1, tab2, tab3, tab4 = st.tabs([
        "💰 예산 조성 (수입)",
        "💸 지출 내역",
        "📊 최종 결산",
        "📒 통합 가계부",
    ])

    with tab1:
        budget_result = _call_with_supported_args(
            render_budget_tab,
            current_project_id=current_project_id,
            project_id=current_project_id,
            user_role=current_user.get("role"),
            current_user=current_user,
        )
        total_budget, total_student_dues, df_members = _normalize_budget_result(
            budget_result, current_project_id,
        )

    with tab2:
        expense_result = _call_with_supported_args(
            render_expense_tab,
            current_project_id=current_project_id,
            project_id=current_project_id,
            user_role=current_user.get("role"),
            current_user=current_user,
        )
        total_expense, df_expenses = _normalize_expense_result(
            expense_result, current_project_id,
        )

    with tab3:
        _call_with_supported_args(
            render_summary_tab,
            selected_project_name=selected_project_name,
            total_budget=total_budget,
            total_expense=total_expense,
            df_expenses=df_expenses,
            df_members=df_members,
            model=client,
            ai_available=ai_available,
            current_project_id=current_project_id,
            project_id=current_project_id,
            user_role=current_user.get("role"),
            current_user=current_user,
        )

    with tab4:
        _call_with_supported_args(
            render_ledger_tab,
            current_project_id=current_project_id,
        )

if __name__ == "__main__":
    main()
