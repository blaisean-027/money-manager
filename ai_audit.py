# ai_audit.py
import pandas as pd
import streamlit as st

from audit import log_action


def run_ai_audit(model, df_expenses: pd.DataFrame, total_budget: int):
    """
    지출 데이터와 총 예산을 바탕으로 Gemini AI 정밀 감사를 수행.
    - REPORT 텍스트와 위험 점수 DataFrame을 반환.
    """
    if df_expenses is None or df_expenses.empty:
        exp_summary = "지출 내역 없음"
    else:
        exp_summary = df_expenses.to_string()

    prompt = f"""
당신은 냉철한 대학 학생회 감사관입니다.

아래 지출 데이터를 분석하고 다음 두 가지를 출력하세요.

1. [REPORT]: 분식회계, 중복 지출, 과다 지출 등 위험 요소가 있는지 텍스트로 보고하세요.
2. [SCORES]: 항목별 '지출 위험도(0~100)'를 아래 형식으로 요약하세요. (높을수록 위험)

형식 예시:
[REPORT] (분석 내용...)
[SCORES] 식비:20, 회식비:80, 홍보비:10

데이터:
{exp_summary} (총 예산: {total_budget})
"""

    response = model.generate_content(prompt)
    full_text = response.text

    # [REPORT] / [SCORES] 분리
    if "[SCORES]" in full_text:
        report_part = full_text.split("[SCORES]")[0].replace("[REPORT]", "")
        score_part = full_text.split("[SCORES]")[1]
    else:
        report_part = full_text
        score_part = ""

    risk_df = None
    if score_part:
        try:
            pairs = [i for i in score_part.split(",") if ":" in i]
            score_dict = {
                k.strip(): int(v.strip())
                for k, v in (p.split(":") for p in pairs)
            }
            risk_df = pd.DataFrame(
                list(score_dict.items()), columns=["항목", "위험 점수"]
            )
        except Exception:
            risk_df = None

    # 세션에도 저장해서 새로고침 시 유지
    st.session_state["ai_audit_report"] = report_part
    if risk_df is not None:
        st.session_state["ai_risk_chart"] = risk_df

    log_action("AI 정밀 감사", "AI 감사관이 리포트와 위험도 차트를 생성함")

    return report_part, risk_df

