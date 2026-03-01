# security.py

import hashlib
import hmac
import io
import json
import random
import string
import time
import datetime

import pandas as pd
import streamlit as st

from audit import log_action
from db import run_query


ROLE_LABELS = {
    "treasurer":      "총무(Treasurer)",
    "deputy":         "차장",
    "president":      "학생회장",
    "vice_president": "부회장",
    "member":         "부원",
}

ROLE_LIMITS = {
    "treasurer":      1,
    "deputy":         1,
    "president":      1,
    "vice_president": 1,
    "member":         None,
}

PRIVILEGED_ROLES = {"treasurer", "admin"}

ALL_PERMISSIONS = [
    ("can_view",           "👁️ 조회"),
    ("can_edit",           "✏️ 수정/입력"),
    ("can_manage_members", "👥 회원 관리"),
    ("can_export",         "📥 내보내기"),
    ("can_archive",        "🗄️ 아카이브"),
    ("can_delete_project", "🗑️ 프로젝트 삭제"),
    ("can_upload_receipt", "🧾 영수증 첨부/AI 파싱"),  # ✅
]

DEFAULT_PERMISSIONS = {
    "treasurer":      ["can_view","can_edit","can_manage_members","can_export","can_archive","can_delete_project","can_upload_receipt"],
    "deputy":         ["can_view","can_edit","can_manage_members","can_export","can_upload_receipt"],
    "president":      ["can_view","can_export"],
    "vice_president": ["can_view","can_export"],
    "member":         ["can_view"],
}

SECURITY_QUESTIONS = [
    "초등학교 이름은?",
    "태어난 도시는?",
    "첫 번째 반려동물 이름은?",
    "가장 좋아하는 음식은?",
    "어머니 성함은?",
    "가장 친한 친구 이름은?",
    "나의 별명은?",
]


# ── 유틸 ─────────────────────────────────────────────────────────────────────
def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()

def verify_password(password: str, password_hash: str) -> bool:
    if not password_hash:
        return False
    return hmac.compare_digest(hash_password(password), password_hash)

def _hash_answer(answer: str) -> str:
    return hashlib.sha256(answer.strip().lower().encode("utf-8")).hexdigest()

def _normalize_role(role: str) -> str:
    if role in {"admin", "총무"}:
        return "treasurer"
    return role or "member"

def _is_quota_full(role: str, statuses=("PENDING", "APPROVED")) -> bool:
    role = _normalize_role(role)
    limit = ROLE_LIMITS.get(role)
    if limit is None:
        return False
    
    # PostgreSQL 파라미터 생성 로직
    params = {"role": role}
    status_conds = []
    for i, s in enumerate(statuses):
        k = f"s{i}"
        status_conds.append(f":{k}")
        params[k] = s
    placeholders = ", ".join(status_conds)
    
    df = run_query(
        f"SELECT COUNT(*) AS cnt FROM approved_users WHERE role = :role AND status IN ({placeholders})",
        params,
        fetch=True,
    )
    count = int(df.iloc[0]["cnt"]) if (df is not None and not df.empty) else 0
    return count >= limit

def _parse_permissions(permissions_json: str, role: str) -> list:
    try:
        if permissions_json:
            return json.loads(permissions_json)
    except Exception:
        pass
    return DEFAULT_PERMISSIONS.get(_normalize_role(role), ["can_view"])

def _gen_temp_password(length: int = 8) -> str:
    chars = string.ascii_letters + string.digits
    return "".join(random.choices(chars, k=length))


# ── 인증 ─────────────────────────────────────────────────────────────────────
def authenticate_user(name, student_id, password=""):
    df = run_query(
        "SELECT role, status, password_hash, permissions FROM approved_users WHERE name = :name AND student_id = :sid",
        {"name": name, "sid": student_id},
        fetch=True,
    )
    if df is None or df.empty:
        return None, "not_found"

    row = df.iloc[0]
    role, status, password_hash, permissions_json = row["role"], row["status"], row["password_hash"], row["permissions"]
    
    role        = _normalize_role(role)
    permissions = _parse_permissions(permissions_json, role)

    if role in PRIVILEGED_ROLES:
        if not password_hash:
            return None, "admin_password_not_set"
        if not password or not verify_password(password, password_hash):
            return None, "bad_password"
        if role == "treasurer" and status in {"PENDING", "APPROVED"}:
            return {"name": name, "student_id": student_id, "role": role, "permissions": permissions}, None

    if status != "APPROVED":
        return None, "not_approved"

    return {"name": name, "student_id": student_id, "role": role, "permissions": permissions}, None


def is_user_approved(name, student_id):
    df = run_query(
        "SELECT status FROM approved_users WHERE name = :name AND student_id = :sid",
        {"name": name, "sid": student_id},
        fetch=True,
    )
    return bool(df is not None and not df.empty and df.iloc[0]["status"] == "APPROVED")


def request_access(name, student_id, role="member", security_question="", security_answer=""):
    role = _normalize_role(role)

    df_existing = run_query(
        "SELECT name, status FROM approved_users WHERE student_id = :sid",
        {"sid": student_id},
        fetch=True,
    )
    if df_existing is not None and not df_existing.empty:
        return False, "already_exists"

    if _is_quota_full(role, statuses=("PENDING", "APPROVED")):
        return False, "quota_full"

    answer_hash = _hash_answer(security_answer) if security_answer.strip() else None

    run_query(
        """
        INSERT INTO approved_users
            (name, student_id, role, status, security_question, security_answer_hash)
        VALUES (:name, :sid, :role, 'PENDING', :sq, :sah)
        """,
        {"name": name, "sid": student_id, "role": role, "sq": security_question or None, "sah": answer_hash},
    )

    df_created = run_query(
        "SELECT 1 FROM approved_users WHERE student_id = :sid AND name = :name AND status = 'PENDING'",
        {"sid": student_id, "name": name},
        fetch=True,
    )
    return bool(df_created is not None and not df_created.empty), None


# ── 비밀번호 찾기 ─────────────────────────────────────────────────────────────
def render_password_reset_ui():
    step = st.session_state.get("reset_step", 1)

    if step == 1:
        st.subheader("1️⃣ 본인 확인")
        r_name = st.text_input("이름", key="reset_name")
        r_sid  = st.text_input("학번", key="reset_sid")

        if st.button("보안 질문 확인", key="reset_step1_btn"):
            if not r_name or not r_sid:
                st.error("이름과 학번을 입력해주세요.")
            else:
                df = run_query(
                    """
                    SELECT security_question, security_answer_hash
                    FROM approved_users
                    WHERE name = :name AND student_id = :sid AND status = 'APPROVED'
                    """,
                    {"name": r_name, "sid": r_sid},
                    fetch=True,
                )
                if df is None or df.empty:
                    st.error("❌ 등록된 계정이 없습니다.")
                elif not df.iloc[0]["security_question"]:
                    st.error("❌ 보안 질문이 설정되지 않았습니다. 총무에게 문의하세요.")
                else:
                    st.session_state["reset_step"]        = 2
                    st.session_state["reset_target_sid"]  = r_sid
                    st.session_state["reset_target_name"] = r_name
                    st.session_state["reset_question"]    = df.iloc[0]["security_question"]
                    st.session_state["reset_ans_hash"]    = df.iloc[0]["security_answer_hash"]
                    st.rerun()

    elif step == 2:
        st.subheader("2️⃣ 보안 질문 답변")
        st.info(f"**질문:** {st.session_state.get('reset_question')}")
        r_answer = st.text_input("답변", key="reset_answer")

        col1, col2 = st.columns(2)
        if col1.button("확인", key="reset_step2_btn"):
            if not r_answer:
                st.error("답변을 입력해주세요.")
            else:
                if hmac.compare_digest(
                    _hash_answer(r_answer),
                    st.session_state.get("reset_ans_hash", ""),
                ):
                    st.session_state["reset_step"] = 3
                    st.rerun()
                else:
                    st.error("❌ 답변이 올바르지 않습니다.")

        if col2.button("↩ 돌아가기", key="reset_back1"):
            for k in ["reset_step","reset_target_sid","reset_target_name","reset_question","reset_ans_hash"]:
                st.session_state.pop(k, None)
            st.rerun()

    elif step == 3:
        st.subheader("3️⃣ 새 비밀번호 설정")
        st.success("✅ 보안 질문 인증 완료!")
        new_pw  = st.text_input("새 비밀번호",     type="password", key="reset_new_pw")
        new_pw2 = st.text_input("새 비밀번호 확인", type="password", key="reset_new_pw2")

        col1, col2 = st.columns(2)
        if col1.button("비밀번호 변경", key="reset_step3_btn", type="primary"):
            if not new_pw:
                st.error("비밀번호를 입력해주세요.")
            elif new_pw != new_pw2:
                st.error("비밀번호가 일치하지 않습니다.")
            elif len(new_pw) < 4:
                st.error("비밀번호는 4자 이상이어야 합니다.")
            else:
                sid  = st.session_state.get("reset_target_sid")
                name = st.session_state.get("reset_target_name")
                run_query(
                    "UPDATE approved_users SET password_hash = :ph WHERE student_id = :sid",
                    {"ph": hash_password(new_pw), "sid": sid},
                )
                run_query(
                    "INSERT INTO reset_logs (student_id, name, reset_by) VALUES (:sid, :name, 'self')",
                    {"sid": sid, "name": name},
                )
                for k in ["reset_step","reset_target_sid","reset_target_name","reset_question","reset_ans_hash"]:
                    st.session_state.pop(k, None)
                st.success("✅ 비밀번호가 변경되었습니다! 다시 로그인해주세요.")

        if col2.button("↩ 돌아가기", key="reset_back2"):
            st.session_state["reset_step"] = 2
            st.rerun()


# ── 총무: 사용자 승인 + 권한 설정 ─────────────────────────────────────────────
def _render_user_approval_manager():
    st.sidebar.markdown("---")
    st.sidebar.header("👤 사용자 승인 관리")

    df_pending = run_query(
        "SELECT student_id, name, role FROM approved_users WHERE status = 'PENDING'",
        fetch=True,
    )

    if df_pending is None or df_pending.empty:
        st.sidebar.info("대기 중인 요청이 없습니다.")
        return

    for _, row in df_pending.iterrows():
        sid, name, role = row["student_id"], row["name"], row["role"]
        normalized  = _normalize_role(role)
        pretty_role = ROLE_LABELS.get(normalized, role)

        with st.sidebar.expander(f"📝 {name} ({sid}) — {pretty_role}"):
            role_options  = list(ROLE_LABELS.keys())
            selected_role = st.selectbox(
                "역할 설정",
                role_options,
                index=role_options.index(normalized) if normalized in role_options else 4,
                format_func=lambda r: ROLE_LABELS.get(r, r),
                key=f"role_sel_{sid}",
            )

            default_perms = DEFAULT_PERMISSIONS.get(selected_role, ["can_view"])
            st.write("**권한 설정:**")
            selected_perms = []
            for perm_key, perm_label in ALL_PERMISSIONS:
                if st.checkbox(
                    perm_label,
                    value=(perm_key in default_perms),
                    key=f"perm_{sid}_{perm_key}",
                ):
                    selected_perms.append(perm_key)

            col1, col2 = st.columns(2)
            if col1.button("✅ 승인", key=f"app_{sid}"):
                if _is_quota_full(selected_role, statuses=("APPROVED",)):
                    st.error(f"'{ROLE_LABELS.get(selected_role)}' 정원이 가득 찼습니다.")
                else:
                    run_query(
                        "UPDATE approved_users SET status='APPROVED', role=:role, permissions=:perms WHERE student_id=:sid",
                        {"role": selected_role, "perms": json.dumps(selected_perms), "sid": sid},
                    )
                    log_action("사용자 승인", f"{name}({sid}) 승인 / 역할: {selected_role} / 권한: {selected_perms}")
                    st.rerun()

            if col2.button("❌ 거절", key=f"rej_{sid}"):
                run_query("DELETE FROM approved_users WHERE student_id = :sid", {"sid": sid})
                log_action("사용자 거절", f"{name}({sid}) 승인 거절")
                st.rerun()


# ── 총무: 승인된 사용자 관리 + 알림 ──────────────────────────────────────────
def _render_user_management_panel():
    st.sidebar.markdown("---")
    st.sidebar.header("🛠️ 사용자 관리")

    df_unread = run_query(
        "SELECT id, name, student_id, reset_at, reset_by FROM reset_logs WHERE is_read = 0 ORDER BY reset_at DESC",
        fetch=True,
    )
    if df_unread is not None and not df_unread.empty:
        st.sidebar.error(f"🔔 비밀번호 초기화 알림 {len(df_unread)}건")
        with st.sidebar.expander("📋 알림 확인"):
            for _, row in df_unread.iterrows():
                log_id, name, sid, reset_at, reset_by = row["id"], row["name"], row["student_id"], row["reset_at"], row["reset_by"]
                who = "본인 직접" if reset_by == "self" else "총무"
                st.write(f"🔑 **{name}** ({sid}) — {who} 초기화 — {reset_at}")
            if st.button("✅ 모두 읽음", key="mark_reset_read"):
                run_query("UPDATE reset_logs SET is_read = 1")
                st.rerun()

    with st.sidebar.expander("👥 승인된 사용자 목록"):
        df_approved = run_query(
            "SELECT student_id, name, role, status FROM approved_users WHERE status IN ('APPROVED','SUSPENDED') ORDER BY role",
            fetch=True,
        )
        if df_approved is None or df_approved.empty:
            st.info("승인된 사용자가 없습니다.")
            return

        for _, row in df_approved.iterrows():
            sid, name, role, status = row["student_id"], row["name"], row["role"], row["status"]
            pretty_role  = ROLE_LABELS.get(_normalize_role(role), role)
            status_emoji = "✅" if status == "APPROVED" else "🚫"
            st.markdown(f"**{status_emoji} {name}** ({sid}) — {pretty_role}")

            col1, col2 = st.columns(2)
            temp_key = f"temp_pw_shown_{sid}"

            if col1.button("🔑 비번 초기화", key=f"reset_pw_{sid}"):
                temp_pw = _gen_temp_password()
                run_query(
                    "UPDATE approved_users SET password_hash = :ph WHERE student_id = :sid",
                    {"ph": hash_password(temp_pw), "sid": sid},
                )
                run_query(
                    "INSERT INTO reset_logs (student_id, name, reset_by) VALUES (:sid, :name, 'treasurer')",
                    {"sid": sid, "name": name},
                )
                st.session_state[temp_key] = temp_pw
                log_action("비밀번호 초기화", f"총무가 {name}({sid}) 비밀번호 초기화")

            if temp_key in st.session_state:
                st.success(f"임시 비밀번호: `{st.session_state[temp_key]}`")
                st.caption("사용자에게 직접 전달 후 변경 안내")
                if st.button("확인했어요", key=f"temp_pw_ok_{sid}"):
                    st.session_state.pop(temp_key, None)
                    st.rerun()

            if status == "APPROVED":
                if col2.button("🚫 비활성화", key=f"suspend_{sid}"):
                    run_query("UPDATE approved_users SET status='SUSPENDED' WHERE student_id=:sid", {"sid": sid})
                    log_action("계정 비활성화", f"{name}({sid}) 계정 비활성화")
                    st.rerun()
            else:
                if col2.button("✅ 재활성화", key=f"activate_{sid}"):
                    run_query("UPDATE approved_users SET status='APPROVED' WHERE student_id=:sid", {"sid": sid})
                    log_action("계정 재활성화", f"{name}({sid}) 계정 재활성화")
                    st.rerun()

            st.markdown("---")


# ── 감사 로그 ─────────────────────────────────────────────────────────────────
def _render_audit_log_sidebar():
    st.sidebar.markdown("---")
    st.sidebar.header("📜 감사 로그 센터")

    if st.sidebar.button("📥 로그 엑셀 백업"):
        df_logs = run_query(
            "SELECT id, timestamp, action, details, user_mode, ip_address, device_info, operator_name FROM audit_logs ORDER BY id DESC",
            fetch=True,
        )
        if df_logs is not None and not df_logs.empty:
            df_logs.columns = ["ID","일시","작업","상세내용","접속자","IP","기기","작업자명"]
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine="openpyxl") as writer:
                df_logs.to_excel(writer, index=False, sheet_name="감사로그")
            st.sidebar.download_button(
                label="파일 저장하기",
                data=output.getvalue(),
                file_name=f"감사로그_백업_{datetime.date.today()}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        else:
            st.sidebar.warning("기록된 로그가 없어.")

    if st.sidebar.checkbox("🗑️ 로그 기록 삭제", key="log_delete_checkbox"):
        st.sidebar.warning("🔐 총무 비밀번호를 입력해야 삭제가 실행됩니다.")
        log_delete_pw = st.sidebar.text_input(
            "총무 비밀번호 입력", type="password", key="log_delete_pw_input"
        )
        if st.sidebar.button("정말 삭제할까?", key="log_delete_confirm_btn"):
            if not log_delete_pw:
                st.sidebar.error("비밀번호를 입력해주세요.")
            else:
                current_user = st.session_state.get("current_user", {})
                verified_user, _ = authenticate_user(
                    current_user.get("name"),
                    current_user.get("student_id"),
                    log_delete_pw,
                )
                if verified_user:
                    run_query("DELETE FROM audit_logs")
                    log_action("로그 삭제", "관리자가 감사 로그를 초기화함")
                    st.sidebar.success("로그 초기화 완료!")
                    time.sleep(1)
                    st.rerun()
                else:
                    st.sidebar.error("❌ 비밀번호가 올바르지 않습니다.")


# ── 루비콘 ────────────────────────────────────────────────────────────────────
def _render_rubicon_admin_controls():
    with st.sidebar.expander("⚔️ Rubicon (관리자 전용)"):
        st.info("총무(Treasurer) 권한 인증됨")
        kill_command = st.text_input("명령어", type="password")
        if kill_command == "루비콘":
            st.sidebar.error("주사위를 던집니다...")
            st.markdown(
                "<style>img { border-radius: 20px; box-shadow: 0 0 50px red; }</style>",
                unsafe_allow_html=True,
            )
            st.image(
                "https://media.giphy.com/media/3o7TKSjRrfIPjeiVyM/giphy.gif",
                caption="운명 결정.",
            )
            time.sleep(4)
            run_query("UPDATE system_config SET [value] = 'LOCKED' WHERE [key] = 'status'")
            log_action("보안 잠금", "루비콘 강을 건넜습니다 (시스템 폐쇄)")
            st.rerun()


def check_rubicon_security(current_user=None):
    df_status = run_query("SELECT [value] FROM system_config WHERE [key] = 'status'", fetch=True)
    status = df_status.iloc[0]["value"] if (df_status is not None and not df_status.empty) else "NORMAL"

    if status == "LOCKED":
        st.markdown(
            "<style>.stApp { background-color: #2c0000; color: white; }</style>",
            unsafe_allow_html=True,
        )
        st.error("🚨 Alea iacta est.")
        st.title("🏛️ 시스템 영구 봉인됨")
        unlock_code = st.text_input("해제 코드:", type="password")
        if unlock_code == "10 legio":
            with st.spinner("10군단 도착..."):
                time.sleep(2)
            run_query("UPDATE system_config SET [value] = 'NORMAL' WHERE [key] = 'status'")
            log_action("보안 해제", "시스템 잠금 해제됨 (10 legio)")
            st.rerun()
        st.stop()

    if current_user and _normalize_role(current_user.get("role")) in PRIVILEGED_ROLES:
        _render_rubicon_admin_controls()
        
