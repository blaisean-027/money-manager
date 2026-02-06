# security.py
import time
import io
import datetime
import pandas as pd
import streamlit as st
from db import run_query
from audit import log_action

# -----------------------------------------------------------------------------
# 🛠️ [신규] 사용자 권한 관련 함수
# -----------------------------------------------------------------------------

def is_user_approved(name, student_id):
    """DB에서 해당 사용자가 'APPROVED' 상태인지 확인"""
    # [cite: 2025-12-31]
    res = run_query(
        "SELECT status FROM approved_users WHERE name = ? AND student_id = ?",
        (name, student_id),
        fetch=True
    )
    if res and res[0][0] == 'APPROVED':
        return True
    return False

def request_access(name, student_id):
    """새로운 사용자가 승인 요청(PENDING)을 보냄"""
    # [cite: 2025-12-31]
    try:
        run_query(
            "INSERT INTO approved_users (name, student_id, status) VALUES (?, ?, 'PENDING')",
            (name, student_id)
        )
        return True
    except:
        return False # 이미 요청했거나 학번 중복인 경우

def _render_user_approval_manager():
    """관리자 전용: 대기 중인 사용자 승인 UI"""
    # [cite: 2025-12-31]
    st.sidebar.markdown("---")
    st.sidebar.header("👤 사용자 승인 관리")
    
    pending_users = run_query(
        "SELECT student_id, name FROM approved_users WHERE status = 'PENDING'",
        fetch=True
    )
    
    if pending_users:
        for sid, name in pending_users:
            st.sidebar.write(f"📝 {name} ({sid})")
            col1, col2 = st.sidebar.columns(2)
            if col1.button("승인", key=f"app_{sid}"):
                run_query("UPDATE approved_users SET status = 'APPROVED' WHERE student_id = ?", (sid,))
                log_action("사용자 승인", f"관리자가 {name}({sid})의 접속을 승인함")
                st.rerun()
            if col2.button("거절", key=f"rej_{sid}"):
                run_query("DELETE FROM approved_users WHERE student_id = ?", (sid,))
                st.rerun()
    else:
        st.sidebar.info("대기 중인 요청이 없습니다.")

# -----------------------------------------------------------------------------
# 🏛️ 기존 보안 로직 (루비콘 & 로그)
# -----------------------------------------------------------------------------

def _render_audit_log_sidebar():
    """감사 로그 엑셀 백업 + 삭제 UI."""
    # [cite: 2025-12-31]
    st.sidebar.markdown("---")
    st.sidebar.header("📜 감사 로그 센터")

    if st.sidebar.button("📥 로그 엑셀 백업"):
        logs = run_query(
            "SELECT id, timestamp, action, details, user_mode, ip_address, device_info, operator_name FROM audit_logs ORDER BY id DESC",
            fetch=True,
        )
        if logs:
            df_logs = pd.DataFrame(logs, columns=["ID", "일시", "작업", "상세내용", "접속자", "IP", "기기", "작업자명"])
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df_logs.to_excel(writer, index=False, sheet_name="감사로그")
            st.sidebar.download_button(label="파일 저장하기", data=output.getvalue(), file_name=f"감사로그_백업_{datetime.date.today()}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        else:
            st.sidebar.warning("기록된 로그가 없어.")

    if st.sidebar.checkbox("🗑️ 로그 기록 삭제"):
        if st.sidebar.button("정말 삭제할까?"):
            run_query("DELETE FROM audit_logs")
            log_action("로그 삭제", "관리자가 감사 로그를 초기화함")
            st.sidebar.success("로그 초기화 완료!")
            time.sleep(1)
            st.rerun()

def check_rubicon_security():
    """시스템 잠금/해제 및 관리자 모드 UI 렌더링"""
    # [cite: 2025-12-31]
    status_row = run_query("SELECT value FROM system_config WHERE key = 'status'", fetch=True)
    status = status_row[0][0] if status_row else "NORMAL"

    if status == "LOCKED":
        st.markdown("<style>.stApp { background-color: #2c0000; color: white; }</style>", unsafe_allow_html=True)
        st.error("🚨 Alea iacta est.")
        st.title("🏛️ 시스템 영구 봉인됨")
        unlock_code = st.text_input("해제 코드:", type="password")
        if unlock_code == "10 legio":
            with st.spinner("10군단 도착..."):
                time.sleep(2)
            run_query("UPDATE system_config SET value = 'NORMAL' WHERE key = 'status'")
            log_action("보안 해제", "시스템 잠금 해제됨 (10 legio)")
            st.rerun()
        st.stop()

    query_params = st.query_params
    secret_mode = query_params.get("mode", [None])

    if secret_mode == "caesar":
        with st.sidebar.expander("⚔️ Imperium (통제권)"):
            st.info("관리자 권한 인증됨")
            kill_command = st.text_input("명령어", type="password")
            if kill_command == "루비콘":
                st.sidebar.error("주사위를 던집니다...")
                st.markdown("<style>img { border-radius: 20px; box-shadow: 0 0 50px red; }</style>", unsafe_allow_html=True)
                st.image("https://media.giphy.com/media/3o7TKSjRrfIPjeiVyM/giphy.gif", caption="운명 결정.")
                time.sleep(4)
                run_query("UPDATE system_config SET value = 'LOCKED' WHERE key = 'status'")
                log_action("보안 잠금", "루비콘 강을 건넜습니다 (시스템 폐쇄)")
                st.rerun()

        # Caesar 모드일 때만 감사 로그와 사용자 승인창이 보임
        _render_audit_log_sidebar()
        _render_user_approval_manager() # ✅ 신규 추가된 승인 관리 UI
        