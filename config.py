# config.py
import streamlit as st
import google.generativeai as genai

# DB 파일 경로
DB_FILE = "finance_pro_v3.db"

# (레거시 탭 호환) 시트/테이블 상수
WS_PROJECTS = "projects"
WS_MEMBERS = "members"
WS_EXPENSES = "expenses"


def init_page():
    """스트림릿 페이지 공통 설정."""
    st.set_page_config(
        page_title="똑똑한 과대표 AI 장부 Pro",
        layout="wide",
        page_icon="🏫",
    )


def init_ai():
    """
    Gemini 모델 초기화.
    - 성공: (model, True)
    - 실패: (None, False)
    """
    try:
        api_key = st.secrets["GOOGLE_API_KEY"]
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-1.5-flash")
        return model, True
    except Exception:
        return None, False


def get_admin_bootstrap():
    """초기 관리자 계정 정보(학번/이름/비밀번호). 비밀번호는 코드 하드코딩 금지."""
    try:
        admin_sid = st.secrets.get("ADMIN_STUDENT_ID", "admin")
        admin_name = st.secrets.get("ADMIN_NAME", "안효현")
        admin_password = st.secrets.get("ADMIN_PASSWORD", "")
    except Exception:
        admin_sid = "admin"
        admin_name = "안효현"
        admin_password = ""
    return admin_sid, admin_name, admin_password

