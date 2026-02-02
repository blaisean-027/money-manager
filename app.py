import streamlit as st
import pandas as pd
import google.generativeai as genai
import database
import receipit

# [중요] 깃허브에 올릴 때 키가 노출되지 않도록 st.secrets 사용
# 스트림릿 클라우드의 Secrets 관리자에서 'GOOGLE_API_KEY'를 가져옴
api_key = st.secrets["GOOGLE_API_KEY"]
analyzer = receipit.Analyzer(api_key)
db = database.DB_Handler()

st.set_page_config(page_title="회계 장부", layout="wide", page_icon="🏫")
st.title("회계장부")

col1, col2 = st.columns([1, 1])

# --- 영수증 업로드 ---
with col1:
    st.header("영수증 업로드")
    file = st.file_uploader("이미지 선택", type=['jpg','png','jpeg'])

    if file:
        st.image(file, caption="업로드된 영수증")

        if st.button("데이터 저장"):
            with st.spinner("업로드 중..."):
                try:
                    result = receipit.Analyzer.analyze(file)
                    st.success("업로드 완료")
                    st.json(result)

                    db.add_row(result)
                    st.toast("저장 완료")
                except Exception as e:
                    st.error(f"오류 발생 : {e}")

# --- 장부 조회 ---
with col2:
    st.header("장부 내역 조회")

    if st.button("새로고침"):
        st.rerun()
    
    df = db.get_all_data()
    st.dataframe(df, use_container_width=True, height=600)