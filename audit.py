# ai_audit.py
import google.generativeai as genai
import pandas as pd
import streamlit as st

def run_ai_audit(model, df_expenses, total_budget):
    """
    고도화된 프롬프트 엔지니어링이 적용된 AI 감사 로직
    """
    # 1. 기초 데이터 가공 (AI가 계산 실수를 하지 않도록 미리 계산해서 떠먹여줌)
    total_spent = df_expenses['amount'].sum() if not df_expenses.empty else 0
    balance = total_budget - total_spent
    usage_rate = (total_spent / total_budget * 100) if total_budget > 0 else 0
    
    # 카테고리별 비중 계산
    if not df_expenses.empty:
        category_stats = df_expenses.groupby('분류')['금액'].sum().reset_index()
        category_stats['비중'] = (category_stats['금액'] / total_spent * 100).round(1)
        expense_summary_str = category_stats.to_markdown(index=False)
    else:
        expense_summary_str = "지출 내역 없음"

    # 2. 🏛️ 작전명령서 (프롬프트) 작성
    # 네가 원하는 '세밀한 가이드라인'을 여기에 모두 담았어!
    prompt = f"""
    ### 1. 역할 정의 (Role)
    당신은 125명 국제학부 학생들의 소중한 학생회비를 감시하는 **'수석 재무 감사관'**입니다.
    당신의 목표는 단 1원의 오차도 없는 투명성을 확보하고, 비효율적인 지출을 찾아내어 학우들의 이익을 보호하는 것입니다.

    ### 2. 분석 대상 데이터 (Context)
    - **총 예산:** {total_budget:,.0f}원
    - **총 지출:** {total_spent:,.0f}원 (집행률: {usage_rate:.1f}%)
    - **현재 잔액:** {balance:,.0f}원
    - **세부 지출 내역:**
    {expense_summary_str}

    ### 3. 감사 가이드라인 (Rules of Engagement)
    **절대 원칙:** 추측성 발언을 금지하고, 오직 제공된 데이터에 기반해서만 분석하십시오.

    **[분석 항목 1: 재정 건전성 평가]**
    - 현재 예산 소진 속도가 적절한지 평가하십시오. (초반인데 50% 이상 썼다면 '위험' 경고)
    - 잔액이 남은 행사 기간을 버티기에 충분한지 냉정하게 판단하십시오.

    **[분석 항목 2: 현미경 지출 분석]**
    - 특정 카테고리(예: 간식비, 회식비)에 예산이 30% 이상 편중되었다면 **'불균형 지출'**로 지적하십시오.
    - 금액이 큰 단일 지출 건이 있다면 그 필요성에 대해 의문을 제기하십시오.

    **[분석 항목 3: 전략적 제언]**
    - 남은 예산을 가장 효율적으로 쓰기 위한 구체적인 액션 플랜을 3가지 제시하십시오.
    - 말투는 **"친근하지만 뼈 때리는 조언을 하는 엘리트 선배"** 톤으로 작성하십시오.

    ### 4. 출력 형식 (Output Format)
    보고서는 반드시 아래의 Markdown 형식을 따르십시오.

    ## 🔍 1. 재정 상태 브리핑
    (내용...)

    ## 🚨 2. 주요 경고 및 리스크
    * **[위험도 높음/중간/낮음]** (항목명): (이유 설명)
    
    ## 💡 3. 향후 자금 운용 전략
    1. (전략 1)
    2. (전략 2)
    3. (전략 3)

    ---
    **"투명한 장부가 신뢰를 만듭니다."**
    """
    
    # 3. 모델 설정 (Temperature를 낮춰서 창의성보다 '정확성'을 높임) [cite: 2025-12-31]
    generation_config = genai.types.GenerationConfig(
        temperature=0.2, # 0에 가까울수록 네가 정한 가이드라인을 칼같이 지킴
    )
    
    # 4. 실행
    response = model.generate_content(prompt, generation_config=generation_config)
    
    # 위험도 데이터 (시각화용) - 로직은 그대로 유지
    if not df_expenses.empty:
        risk_data = [{"항목": row['분류'], "위험도": row['비중']} for _, row in category_stats.iterrows()]
    else:
        risk_data = []
    
    risk_df = pd.DataFrame(risk_data) if risk_data else pd.DataFrame(columns=["항목", "위험도"])
    
    return response.text, risk_df
