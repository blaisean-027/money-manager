import streamlit as st
from groq import Groq

DB_FILE = "finance_pro_v3.db"

WS_PROJECTS = "projects"
WS_MEMBERS  = "members"
WS_EXPENSES = "expenses"

def init_page():
    st.set_page_config(
        page_title="똑똑한 과대표 AI 장부 Pro",
        layout="wide",
        page_icon="🏫",
    )

def init_ai():
    try:
        api_key = st.secrets["GROQ_API_KEY"]
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
    try:
        admin_sid      = st.secrets.get("ADMIN_STUDENT_ID", "admin")
        admin_name     = st.secrets.get("ADMIN_NAME", "안효현")
        admin_password = st.secrets.get("ADMIN_PASSWORD", "")
    except Exception:
        admin_sid      = "admin"
        admin_name     = "안효현"
        admin_password = ""
    return admin_sid, admin_name, admin_password

