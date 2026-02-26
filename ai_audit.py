import pandas as pd
from groq import Groq

def parse_receipt_image(client, image_bytes: bytes, mime_type: str = "image/jpeg") -> dict:
    """
    ⚠️ Groq은 이미지 입력 미지원 → 텍스트 안내 반환
    """
    return {
        "date": None, "item": "", "amount": 0,
        "category": "기타",
        "raw_text": "영수증 이미지 파싱은 Gemini 전용 기능입니다. 수동 입력해 주세요."
    }

def run_ai_audit(client, df_expenses: pd.DataFrame, total_budget: int):
    total_spent  = int(df_expenses["amount"].sum()) if not df_expenses.empty else 0
    balance      = total_budget - total_spent
    usage_rate   = (total_spent / total_budget * 100) if total_budget > 0 else 0
    avg_per_item = (total_spent / len(df_expenses)) if not df_expenses.empty else 0

    if not df_expenses.empty:
        cat_col = "분류" if "분류" in df_expenses.columns else "category"
        amt_col = "금액" if "금액" in df_expenses.columns else "amount"

        category_stats = (
            df_expenses.groupby(cat_col)[amt_col]
            .sum().reset_index()
            .rename(columns={amt_col: "합계"})
        )
        category_stats["비중(%)"] = (category_stats["합계"] / total_spent * 100).round(1)
        category_stats = category_stats.sort_values("합계", ascending=False)
        expense_summary_str = category_stats.to_markdown(index=False)

        item_col = "내역" if "내역" in df_expenses.columns else "item"
        date_col = "날짜" if "날짜" in df_expenses.columns else "date"
        top3_str = (
            df_expenses.nlargest(3, amt_col)[[date_col, cat_col, item_col, amt_col]]
            .to_markdown(index=False)
        )
        danger_cats = category_stats[category_stats["비중(%)"] >= 30][cat_col].tolist()
        danger_str  = ", ".join(danger_cats) if danger_cats else "없음"
    else:
        expense_summary_str = "지출 내역 없음"
        top3_str = "없음"
        danger_str = "없음"

    if usage_rate >= 90:
        budget_status = "🔴 심각 (잔액 10% 미만)"
    elif usage_rate >= 70:
        budget_status = "🟠 경고 (잔액 30% 미만)"
    elif usage_rate >= 50:
        budget_status = "🟡 주의 (절반 이상 소진)"
    else:
        budget_status = "🟢 양호"

    prompt = f"""
당신은 대한민국 최고 수준의 **공인 재무 감사관**이자 학생회 재정 전문 컨설턴트입니다.
다년간의 감사 경험을 바탕으로, 단 한 건의 비정상 지출도 놓치지 않는 것으로 유명합니다.
지금 당신 앞에 125명 국제학부 학생들의 **한 학기 학생회비 장부**가 펼쳐져 있습니다.

---

## 📊 감사 대상 재무 데이터

| 항목 | 수치 |
|------|------|
| 총 예산 | {total_budget:,.0f}원 |
| 총 지출 | {total_spent:,.0f}원 |
| 예산 집행률 | {usage_rate:.1f}% → {budget_status} |
| 현재 잔액 | {balance:,.0f}원 |
| 건당 평균 지출 | {avg_per_item:,.0f}원 |
| 30% 초과 편중 카테고리 | {danger_str} |

### 카테고리별 지출 분석
{expense_summary_str}

### 고액 지출 TOP 3
{top3_str}

---

## 🎯 감사 수행 지침

**[철칙]**
- 제공된 데이터 외 추측성 발언 절대 금지
- 수치는 반드시 원문 데이터 기반으로만 인용
- 칭찬보다 문제점 발굴에 집중

**[분석 항목 1: 재정 건전성 종합 평가]**
- 예산 집행률 {usage_rate:.1f}%가 현 시점에서 적절한지 판단
- 잔액 {balance:,.0f}원이 충분한지 냉정하게 평가

**[분석 항목 2: 현미경 지출 분석]**
- 30% 이상 편중 카테고리를 **'불균형 지출'**로 공식 지적
- TOP 3 고액 지출 타당성 검토

**[분석 항목 3: 리스크 레이더]**
- 예산 초과 가능성 및 원인 분석
- 투명성 관련 잠재적 문제점 지적

**[분석 항목 4: 전략적 자금 운용 제언]**
- 잔액 {balance:,.0f}원 최적 배분 방안 3가지 (수치 포함)
- 차기 예산 편성 교훈

**[말투]** 친근하지만 뼈 때리는 엘리트 선배 톤

---

## 📋 출력 형식

## 🔍 1. 재정 상태 브리핑
## 🚨 2. 주요 경고 및 리스크
* **[위험도: 높음/중간/낮음]** **(항목명)**: (설명)
## 🔬 3. 지출 심층 분석
## 💡 4. 향후 자금 운용 전략
1. **[전략명]**: (액션 + 수치)
2. **[전략명]**: (액션 + 수치)
3. **[전략명]**: (액션 + 수치)
## 📌 5. 감사관 최종 소견

---
*"투명한 장부가 신뢰를 만들고, 신뢰가 학생회를 만듭니다."*
"""

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        max_tokens=2048,
    )

    if not df_expenses.empty:
        risk_data = [
            {"항목": row[cat_col], "위험도": row["비중(%)"]}
            for _, row in category_stats.iterrows()
        ]
    else:
        risk_data = []

    risk_df = (
        pd.DataFrame(risk_data) if risk_data
        else pd.DataFrame(columns=["항목", "위험도"])
    )

    return response.choices[0].message.content, risk_df

