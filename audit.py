# audit.py
import sqlite3
import streamlit as st
from streamlit.web.server.websocket_headers import _get_websocket_headers

from config import DB_FILE


def get_user_info():
    """사용자의 IP와 기기 정보를 추출."""
    try:
        headers = _get_websocket_headers()
        ip = headers.get("X-Forwarded-For", "Unknown IP")
        user_agent = headers.get("User-Agent", "Unknown Device")
        return ip, user_agent
    except Exception:
        return "Unknown IP", "Unknown Device"


def log_action(action: str, details: str):
    """
    모든 중요 행동을 DB에 기록하는 CCTV 함수.
    - 관리자 모드 여부에 따라 user_mode / operator_name 처리.
    """
    query_params = st.query_params
    is_admin = query_params.get("mode") == "caesar"
    user_mode = "관리자(Caesar)" if is_admin else "일반 사용자"

    ip_addr, device = get_user_info()

    op_name = st.session_state.get("operator_name_input", "익명")
    if is_admin:
        op_name = "관리자(본인)"

    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO audit_logs (
                action, details, user_mode,
                ip_address, device_info, operator_name
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (action, details, user_mode, ip_addr, device, op_name),
        )
        conn.commit()
