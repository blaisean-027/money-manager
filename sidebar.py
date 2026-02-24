# sidebar.py
import io
import zipfile

import pandas as pd
import streamlit as st

from audit import log_action
from db import run_query
from export_excel import create_settlement_excel
from security import (
    PRIVILEGED_ROLES,
    ROLE_LABELS,
    _render_audit_log_sidebar,
    _render_user_approval_manager,
    authenticate_user,
    request_access,
)

ROLE_OPTIONS = ["treasurer", "deputy", "president", "vice_president", "member"]


def _build_project_excel(project_id: int, project_name: str) -> bytes:
    budget_total_row = run_query(
        "SELECT COALESCE(SUM(amount), 0) FROM budget_entries WHERE project_id = ?",
        (project_id,),
        fetch=True,
    )
    budget_total = int(budget_total_row[0][0]) if budget_total_row else 0

    members_data = run_query(
        "SELECT paid_date, name, student_id, deposit_amount, note FROM members WHERE project_id = ?",
        (project_id,),
        fetch=True,
    )
    if members_data:
        df_members = pd.DataFrame(
            members_data, columns=["납부일", "이름", "학번", "납부액", "비고"]
        )
        total_student_dues = int(df_members["납액"].sum())
    else:
        df_members = pd.DataFrame(columns=["납부일", "이름", "학번", "납부액", "비고"])
        total_student_dues = 0

    expense_rows = run_query(
        "SELECT date, category, item, amount FROM expenses WHERE project_id = ? ORDER BY date DESC",
        (project_id,),
        fetch=True,
    )
    if expense_rows:
        df_expenses = pd.DataFrame(expense_rows, columns=["날짜", "분류", "내역", "금액"])
        total_expense = int(df_expenses["금액"].sum())
    else:
        df_expenses = pd.DataFrame(columns=["날짜", "분류", "내역", "금액"])
        total_expense = 0

    total_budget = budget_total + total_student_dues
    final_balance = total_budget - total_expense

    return create_settlement_excel(
        project_name=project_name,
        total_budget=total_budget,
        total_expense=total_expense,
        final_balance=final_balance,
        df_expenses=df_expenses,
        df_members=df_members,
    )


def _build_all_projects_zip(project_list):
    mem_file = io.BytesIO()
    with zipfile.ZipFile(mem_file, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for pid, pname in project_list:
            xlsx_bytes = _build_project_excel(pid, pname)
            safe_name = pname.replace("/", "_").replace("\\", "_")
            zf.writestr(f"{safe_name}_최종결산.xlsx", xlsx_bytes)
    return mem_file.getvalue()


def _render_login_center():
    st.markdown("## 🔐 로그인")
    st.info("로그인 전에는 왼쪽 사이드바를 숨기고, 중앙에서 먼저 로그인합니다.")

    with st.form("center_login_form", clear_on_submit=False):
        input_name = st.text_input("이름 (실명)")
        input_sid = st.text_input("학번")
        input_password = st.text_input("비밀번호 (총무/관리자 필수)", type="password")
        input_role = st.selectbox(
            "처음 이용자라면 신청 역할 선택",
            ROLE_OPTIONS,
            format_func=lambda role: ROLE_LABELS.get(role, role),
        )

        col1, col2 = st.columns(2)
        login_submit = col1.form_submit_button("로그인")
        request_submit = col2.form_submit_button("접속 승인 요청")

    if login_submit:
        current_user, auth_error = authenticate_user(input_name, input_sid, input_password)
        if current_user:
            st.session_state["current_user"] = current_user
            st.session_state["operator_name_input"] = current_user.get("name", "익명")
            st.success("로그인 성공! 사이드바를 활성화합니다.")
            st.rerun()

        if auth_error in {"bad_password", "admin_password_not_set"}:
            st.error("❌ 총무(관리자) 비밀번호가 올바르지 않거나 설정되지 않았습니다.")
        elif auth_error == "not_found":
            st.error("❌ 등록되지 않은 계정입니다. 아래에서 승인 요청을 먼저 해주세요.")
        elif auth_error == "not_approved":
            st.error("❌ 승인 대기 중입니다. 총무 승인 후 로그인 가능합니다.")
        else:
            st.error("❌ 로그인 실패")

    if request_submit:
        ok, reason = request_access(input_name, input_sid, input_role)
        if ok:
            st.warning("요청 완료! 총무의 승인을 기다려주세요.")
        elif reason == "quota_full":
            st.info("해당 역할 정원이 가득 찼습니다. 다른 역할로 신청해주세요.")
        else:
            st.info("이미 승인 요청 중이거나 정보가 다릅니다.")

    st.stop()


def render_sidebar(ai_available: bool):
    """로그인 후에만 왼쪽 사이드바를 렌더링."""
    current_user = st.session_state.get("current_user")
    if not current_user:
        st.markdown(
            """
            <style>
            [data-testid="stSidebar"] {display: none;}
            </style>
            """,
            unsafe_allow_html=True,
        )
        _render_login_center()

    with st.sidebar:
        st.header("📂 행사(프로젝트) 센터")
        st.success(f"✅ 로그인: {current_user.get('name')} ({current_user.get('student_id')})")

        if st.button("로그아웃"):
            st.session_state.pop("current_user", None)
            st.rerun()

        if current_user.get("role") in PRIVILEGED_ROLES:
            st.sidebar.success("👑 총무(Treasurer) 권한으로 로그인됨")
            _render_user_approval_manager()
            _render_audit_log_sidebar()

        st.markdown("---")
        st.subheader("➕ 프로젝트 생성")
        st.caption("프로젝트명만 먼저 만들고, 예산/예비비는 '예산 조성' 탭에서 입력합니다.")
        new_project_name = st.text_input("행사명 (예: 2026 해오름제)")

        if st.button("행사 생성"):
            if not new_project_name.strip():
                st.warning("행사명을 입력해줘!")
            else:
                try:
                    run_query(
                        "INSERT INTO projects (name) VALUES (?)",
                        (new_project_name.strip(),),
                    )
                    log_action("행사 생성", f"새 행사 '{new_project_name}' 생성")
                    st.success(f"'{new_project_name}' 준비 시작!")
                    st.rerun()
                except Exception:
                    st.warning("이미 있는 이름이야.")

        project_list = run_query(
            "SELECT id, name FROM projects ORDER BY created_at DESC, id DESC",
            fetch=True,
        )
        if not project_list:
            st.info("👈 행사를 먼저 만들어줘!")
            st.stop()

        project_dict = {name: pid for pid, name in project_list}
        selected_project_name = st.selectbox("현재 관리 중인 행사", list(project_dict.keys()))
        current_project_id = project_dict[selected_project_name]

        st.markdown("---")
        st.subheader("🧾 프로젝트 추출")

        single_bytes = _build_project_excel(current_project_id, selected_project_name)
        st.download_button(
            "📥 단일 프로젝트 추출 (Excel)",
            data=single_bytes,
            file_name=f"{selected_project_name}_최종결산.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        all_zip = _build_all_projects_zip(project_list)
        st.download_button(
            "📦 전체 프로젝트 추출 (ZIP)",
            data=all_zip,
            file_name="전체프로젝트_결산모음.zip",
            mime="application/zip",
        )

        st.divider()
        if ai_available:
            st.success("🤖 AI 감사관: 연결됨")
        else:
            st.error("🤖 AI 감사관: 오프라인 (API 키 확인 필요)")

    return current_user, selected_project_name, current_project_id

