# sidebar.py

import io
import zipfile

import pandas as pd
import streamlit as st

from audit import log_action
from db import run_query
from export_excel import create_settlement_excel
from archive.archive_service import archive_project, delete_archived_project_data

from security import (
    PRIVILEGED_ROLES,
    ROLE_LABELS,
    SECURITY_QUESTIONS,
    _render_audit_log_sidebar,
    _render_user_approval_manager,
    _render_user_management_panel,
    authenticate_user,
    render_password_reset_ui,
    request_access,
)

ROLE_OPTIONS = ["treasurer", "deputy", "president", "vice_president", "member"]


# ── 권한 헬퍼 ─────────────────────────────────────────────────────────────────
def _can_archive(current_user: dict) -> bool:
    permissions = current_user.get("permissions", [])
    if isinstance(permissions, list) and "can_archive" in permissions:
        return True
    return current_user.get("role") in PRIVILEGED_ROLES


def _can_delete_project(current_user: dict) -> bool:
    permissions = current_user.get("permissions", [])
    if isinstance(permissions, list) and "can_delete_project" in permissions:
        return True
    return current_user.get("role") in PRIVILEGED_ROLES


# ── session_state 키 헬퍼 ─────────────────────────────────────────────────────
def _archive_key(suffix, project_id): return f"archive_{suffix}_{project_id}"
def _delete_key(suffix, project_id):  return f"delete_{suffix}_{project_id}"

def _clear_archive_state(project_id):
    for s in ("payload","filename","ready","archived_by","archive_reason"):
        st.session_state.pop(_archive_key(s, project_id), None)

def _clear_delete_state(project_id):
    st.session_state.pop(_delete_key("confirm", project_id), None)


# ── 아카이브 콜백 ─────────────────────────────────────────────────────────────
def _on_delete_confirm_click(project_id):
    delete_archived_project_data(
        project_id=project_id,
        archived_by=st.session_state.get(_archive_key("archived_by", project_id), "unknown"),
        archive_reason=st.session_state.get(_archive_key("archive_reason", project_id), ""),
        filename=st.session_state.get(_archive_key("filename", project_id), ""),
    )
    _clear_archive_state(project_id)


def _on_project_delete_click(project_id, current_user):
    delete_archived_project_data(
        project_id=project_id,
        archived_by=current_user.get("name", "unknown"),
        archive_reason="프로젝트 직접 삭제",
        filename="",
        delete_project=True,
    )
    _clear_delete_state(project_id)


# ── 아카이브 UI ───────────────────────────────────────────────────────────────
def _render_admin_archive_ui(current_user, project_id):
    if not _can_archive(current_user):
        return

    st.markdown("---")
    st.subheader("🗄️ 프로젝트 아카이브")
    is_ready = st.session_state.get(_archive_key("ready", project_id), False)

    if not is_ready:
        archive_reason = st.text_area("아카이브 사유 (필수)", key=f"archive_reason_input_{project_id}")
        if st.button("📦 아카이브 파일 준비", key=f"prepare_archive_{project_id}"):
            if not archive_reason.strip():
                st.error("아카이브 사유를 입력해야 합니다.")
            else:
                try:
                    filename, archive_json = archive_project(project_id, current_user, archive_reason.strip())
                    st.session_state[_archive_key("payload", project_id)]        = archive_json
                    st.session_state[_archive_key("filename", project_id)]       = filename
                    st.session_state[_archive_key("archived_by", project_id)]    = current_user.get("name","unknown")
                    st.session_state[_archive_key("archive_reason", project_id)] = archive_reason.strip()
                    st.session_state[_archive_key("ready", project_id)]          = True
                    st.rerun()
                except Exception as e:
                    st.error(f"아카이브 준비 실패: {e}")
        return

    st.success("✅ 아카이브 파일 준비 완료.")
    st.warning("⚠️ 다운로드 후 아래 '삭제 확인' 버튼을 눌러야 DB에서 삭제됩니다.")
    st.download_button(
        "📥 아카이브 JSON 다운로드",
        data=st.session_state[_archive_key("payload", project_id)],
        file_name=st.session_state[_archive_key("filename", project_id)],
        mime="application/json",
        key=f"download_archive_{project_id}",
    )
    st.error("🗑️ 다운로드를 완료했다면 아래 버튼으로 DB 데이터를 삭제하세요.")
    col1, col2 = st.columns(2)
    with col1:
        st.button("✅ 다운로드 완료 → DB 삭제 실행", key=f"confirm_delete_{project_id}",
                  on_click=_on_delete_confirm_click, args=(project_id,), type="primary")
    with col2:
        if st.button("❌ 취소", key=f"cancel_archive_{project_id}"):
            _clear_archive_state(project_id)
            st.rerun()


# ── 프로젝트 삭제 UI ──────────────────────────────────────────────────────────
def _render_project_delete_ui(current_user, project_id, project_name):
    if not _can_delete_project(current_user):
        return

    st.markdown("---")
    st.subheader("🗑️ 프로젝트 삭제")
    confirm_key  = _delete_key("confirm", project_id)
    is_confirming = st.session_state.get(confirm_key, False)

    if not is_confirming:
        if st.button(f"🗑️ '{project_name}' 프로젝트 삭제", key=f"delete_project_btn_{project_id}"):
            st.session_state[confirm_key] = True
            st.rerun()
        return

    st.error(f"⚠️ **'{project_name}'** 의 모든 데이터가 영구 삭제됩니다. 복구 불가능합니다.")
    st.warning("🔐 총무 비밀번호를 입력해야 삭제가 실행됩니다.")
    input_pw = st.text_input("총무 비밀번호 입력", type="password", key=f"delete_pw_input_{project_id}")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("🔴 최종 확인 → 완전 삭제", key=f"confirm_project_delete_{project_id}", type="primary"):
            if not input_pw:
                st.error("비밀번호를 입력해주세요.")
            else:
                verified_user, _ = authenticate_user(
                    current_user.get("name"), current_user.get("student_id"), input_pw
                )
                if verified_user:
                    _on_project_delete_click(project_id, current_user)
                    st.rerun()
                else:
                    st.error("❌ 비밀번호가 올바르지 않습니다.")
    with col2:
        if st.button("취소", key=f"cancel_project_delete_{project_id}"):
            _clear_delete_state(project_id)
            st.rerun()


# ── Excel / ZIP 빌더 ──────────────────────────────────────────────────────────
def _build_project_excel(project_id, project_name):
    budget_total_row = run_query(
        "SELECT COALESCE(SUM(amount), 0) FROM budget_entries WHERE project_id = ?",
        (project_id,), fetch=True,
    )
    budget_total = int(budget_total_row[0][0]) if budget_total_row else 0

    members_data = run_query(
        "SELECT paid_date, name, student_id, deposit_amount, note FROM members WHERE project_id = ?",
        (project_id,), fetch=True,
    )
    if members_data:
        df_members = pd.DataFrame(members_data, columns=["납부일","이름","학번","납부액","비고"])
        total_student_dues = int(df_members["납부액"].sum())
    else:
        df_members = pd.DataFrame(columns=["납부일","이름","학번","납부액","비고"])
        total_student_dues = 0

    expense_rows = run_query(
        "SELECT date, category, item, amount FROM expenses WHERE project_id = ? ORDER BY date DESC",
        (project_id,), fetch=True,
    )
    if expense_rows:
        df_expenses = pd.DataFrame(expense_rows, columns=["날짜","분류","내역","금액"])
        total_expense = int(df_expenses["금액"].sum())
    else:
        df_expenses = pd.DataFrame(columns=["날짜","분류","내역","금액"])
        total_expense = 0

    return create_settlement_excel(
        project_name=project_name,
        total_budget=budget_total + total_student_dues,
        total_expense=total_expense,
        final_balance=(budget_total + total_student_dues) - total_expense,
        df_expenses=df_expenses,
        df_members=df_members,
    )


def _build_all_projects_zip(project_list):
    mem_file = io.BytesIO()
    with zipfile.ZipFile(mem_file, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for pid, pname in project_list:
            safe = pname.replace("/","_").replace("\\","_")
            zf.writestr(f"{safe}_최종결산.xlsx", _build_project_excel(pid, pname))
    return mem_file.getvalue()


# ── 로그인 화면 ───────────────────────────────────────────────────────────────
def _render_login_center():
    st.markdown("## 🔐 로그인")
    st.info("로그인 전에는 왼쪽 사이드바를 숨기고, 중앙에서 먼저 로그인합니다.")

    tab_login, tab_register = st.tabs(["🔑 로그인", "📝 접속 승인 요청"])

    # ── 로그인 탭 ──────────────────────────────────────────────────────────
    with tab_login:
        with st.form("login_form", clear_on_submit=False):
            input_name     = st.text_input("이름 (실명)")
            input_sid      = st.text_input("학번")
            input_password = st.text_input("비밀번호 (총무/관리자 필수)", type="password")
            login_submit   = st.form_submit_button("로그인")

        if login_submit:
            current_user, auth_error = authenticate_user(input_name, input_sid, input_password)
            if current_user:
                st.session_state["current_user"]          = current_user
                st.session_state["operator_name_input"]   = current_user.get("name","익명")
                st.success("로그인 성공! 사이드바를 활성화합니다.")
                st.rerun()
            elif auth_error in {"bad_password","admin_password_not_set"}:
                st.error("❌ 비밀번호가 올바르지 않거나 설정되지 않았습니다.")
            elif auth_error == "not_found":
                st.error("❌ 등록되지 않은 계정입니다. '접속 승인 요청' 탭에서 신청해주세요.")
            elif auth_error == "not_approved":
                st.error("❌ 승인 대기 중입니다. 총무 승인 후 로그인 가능합니다.")
            else:
                st.error("❌ 로그인 실패")

        # 비밀번호 찾기
        with st.expander("🔑 비밀번호를 잊으셨나요?"):
            render_password_reset_ui()

    # ── 회원가입 탭 ────────────────────────────────────────────────────────
    with tab_register:
        with st.form("register_form", clear_on_submit=False):
            r_name = st.text_input("이름 (실명)")
            r_sid  = st.text_input("학번")
            r_role = st.selectbox(
                "신청 역할",
                ROLE_OPTIONS,
                format_func=lambda role: ROLE_LABELS.get(role, role),
            )

            st.markdown("---")
            st.caption("🔐 보안 질문은 비밀번호 분실 시 본인 인증에 사용됩니다.")
            r_question = st.selectbox("보안 질문 선택", SECURITY_QUESTIONS)
            r_answer   = st.text_input("보안 질문 답변", type="password")

            request_submit = st.form_submit_button("접속 승인 요청")

        if request_submit:
            if not r_name or not r_sid:
                st.error("이름과 학번을 입력해주세요.")
            elif not r_answer.strip():
                st.error("보안 질문 답변을 입력해주세요.")
            else:
                ok, reason = request_access(r_name, r_sid, r_role, r_question, r_answer)
                if ok:
                    st.success("✅ 요청 완료! 총무의 승인을 기다려주세요.")
                elif reason == "quota_full":
                    st.info("해당 역할 정원이 가득 찼습니다. 다른 역할로 신청해주세요.")
                elif reason == "already_exists":
                    st.info("이미 등록된 계정입니다.")
                else:
                    st.error("요청 중 오류가 발생했습니다.")

    st.stop()


# ── 메인 사이드바 ─────────────────────────────────────────────────────────────
def render_sidebar(ai_available: bool):
    current_user = st.session_state.get("current_user")
    if not current_user:
        st.markdown("""
            <style>[data-testid="stSidebar"] {display: none;}</style>
        """, unsafe_allow_html=True)
        _render_login_center()
        return

    with st.sidebar:
        st.header("📂 행사(프로젝트) 센터")
        st.success(f"✅ 로그인: {current_user.get('name')} ({current_user.get('student_id')})")

        if st.button("로그아웃"):
            st.session_state.pop("current_user", None)
            st.rerun()

        if current_user.get("role") in PRIVILEGED_ROLES:
            st.sidebar.success("👑 총무(Treasurer) 권한으로 로그인됨")
            _render_user_approval_manager()
            _render_user_management_panel()    # ✅ 사용자 관리 + 알림
            _render_audit_log_sidebar()

        st.markdown("---")
        st.subheader("🏷️ 프로젝트 생성")
        st.caption("프로젝트명만 먼저 만들고, 예산/예비비는 '예산 조성' 탭에서 입력합니다.")
        new_project_name = st.text_input("행사명 (예: 2026 해오름제)")

        if st.button("행사 생성"):
            if not new_project_name.strip():
                st.warning("행사명을 입력해줘!")
            else:
                try:
                    run_query("INSERT INTO projects (name) VALUES (?)", (new_project_name.strip(),))
                    log_action("행사 생성", f"새 행사 '{new_project_name}' 생성")
                    st.success(f"'{new_project_name}' 준비 시작!")
                    st.rerun()
                except Exception:
                    st.warning("이미 있는 이름이야.")

        project_list = run_query(
            "SELECT id, name FROM projects ORDER BY created_at DESC, id DESC", fetch=True
        )
        if not project_list:
            st.info("👈 행사를 먼저 만들어줘!")
            st.stop()

        project_dict          = {name: pid for pid, name in project_list}
        selected_project_name = st.selectbox("현재 관리 중인 행사", list(project_dict.keys()))
        current_project_id    = project_dict[selected_project_name]

        _render_admin_archive_ui(current_user, current_project_id)
        _render_project_delete_ui(current_user, current_project_id, selected_project_name)

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

