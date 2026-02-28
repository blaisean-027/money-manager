import os
import streamlit as st
from groq import Groq

DB_FILE = "finance_pro_v3.db"

WS_PROJECTS = "projects"
WS_MEMBERS  = "members"
WS_EXPENSES = "expenses"


def _secret_get(*keys, default=None):
    """top-level secrets -> connections.sql -> env 순서로 조회"""
    for key in keys:
        try:
            if key in st.secrets:
                return st.secrets[key]
        except Exception:
            pass

        try:
            connections = st.secrets.get("connections", {})
            sql_cfg = connections.get("sql", {}) if isinstance(connections, dict) else {}
            if key in sql_cfg:
                return sql_cfg[key]
        except Exception:
            pass

        val = os.getenv(key)
        if val:
            return val

    return default

def init_page():
    st.set_page_config(
        page_title="똑똑한 과대표 AI 장부 Pro",
        layout="wide",
        page_icon="🏫",
    )

def init_ai():
    try:
        api_key = _secret_get("GROQ_API_KEY")
        if not api_key:
            raise ValueError("GROQ_API_KEY missing")

        client  = Groq(api_key=api_key)
        client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=5,
        )
        return client, True
    except Exception:
        return None, False

def get_admin_bootstrap():
    admin_sid      = _secret_get("ADMIN_STUDENT_ID", default="admin")
    admin_name     = _secret_get("ADMIN_NAME", default="안효현")
    admin_password = _secret_get("ADMIN_PASSWORD", default="")
    return admin_sid, admin_name, admin_password
