# audit.py
# audit.py
import sqlite3

from streamlit.web.server.websocket_headers import _get_websocket_headers
import streamlit as st

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
    """중요 행동을 DB에 기록."""
    current_user = st.session_state.get("current_user", {})
    role = current_user.get("role", "member")
    name = current_user.get("name", st.session_state.get("operator_name_input", "익명"))

    if role in {"treasurer", "admin"}:
        user_mode = "관리자(Treasurer)"
    else:
        user_mode = "일반 사용자"

    ip_addr, device = get_user_info()

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
            (action, details, user_mode, ip_addr, device, name),
        )
        conn.commit()


