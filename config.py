# config.py
import streamlit as st
import google.generativeai as genai

# DB 파일 경로 (원래 코드 그대로)
DB_FILE = "finance_pro_v3.db"


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
