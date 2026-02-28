# tabs/tab_summary.py
import pandas as pd
import streamlit as st

from ai_audit import run_ai_audit
from export_excel import create_settlement_excel


def render_summary_tab(
    selected_project_name: str,
    total_budget: int,
    total_expense: int,
    df_expenses: pd.DataFrame,
    df_members: pd.DataFrame,
    model,                  
    ai_available: bool,
    **kwargs  # app.py에서 넘겨주는 기타 정보들을 안전하게 흡수
):
    """TAB3: 최종 결산 대시보드 + 시각화 + 감사 + 엑셀 다운로드."""
    st.header("⚖️ 최종 결산 대시보드")

    final_balance = total_budget - total_expense
    usage_rate    = (total_expense / total_budget * 100) if total_budget > 0 else 0

    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    kpi1.metric("총 예산",    f"{total_budget:,.0f}원")
    kpi2.metric("총 지출",    f"{total_expense:,.0f}원")
    kpi3.metric("현재 잔액",  f"{final_balance:,.0f}원")
    kpi4.metric("예산 소진율", f"{usage_rate:.1f}%")

    st.subheader("📊 재정 시각화 리포트")
    col_v1, col_v2 = st.columns(2)

    with col_v1:
        st.write("📂 **분류별 지출 비중**")
        if df_expenses is not None and not df_expenses.empty:
            chart_data = df_expenses.groupby("분류")["금액"].sum()
            st.bar_chart(chart_data, color="#ff4b4b")
        else:
            st.info("지출 내역이 입력되면 차트가 나타나.")

    with col_v2:
        st.write("📈 **예산 대비 지출 현황**")
        compare_df = pd.DataFrame(
            {"항목": ["총 예산", "총 지출"], "금액": [total_budget, total_expense]}
        ).set_index("항목")
        st.bar_chart(compare_df, color="#4b86ff")

    st.write(f"📉 **전체 예산 집행률 ({usage_rate:.1f}%)**")
    st.progress(min(usage_rate / 100, 1.0))

    st.divider()
    col_ai, col_xls = st.columns([2, 1])

    # ── AI 감사 ───────────────────────────────────────────────────────────
    with col_ai:
        st.subheader("🤖 AI 총무 정밀 감사 & 분석")

        if ai_available and model is not None:
            if st.button("🚨 AI 장부 정밀 감사 실행"):
                with st.spinner("재정 데이터를 AI가 정밀 분석 중..."):
                    try:
                        report_text, risk_df = run_ai_audit(
                            model,          
                            df_expenses,
                            total_budget,
                        )
                        st.session_state["ai_audit_report"] = report_text
                        st.session_state["ai_risk_chart"]   = risk_df
                        st.success("감사 완료! 아래 결과를 확인하세요.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"분석 중 오류 발생: {e}")
        else:
            st.warning("⚠️ AI 기능이 꺼져있어. (API 키 설정 필요)")

        # 감사 결과 출력
        if "ai_audit_report" in st.session_state:
            st.info("📑 AI 감사 보고서")
            st.markdown(st.session_state["ai_audit_report"])

        if "ai_risk_chart" in st.session_state:
            st.write("📊 **AI 선정 지출 위험도 분석** (높을수록 정밀 조사 필요)")
            risk_df = st.session_state["ai_risk_chart"]
            if not risk_df.empty:
                st.bar_chart(risk_df.set_index("항목"), color="#d33682")

    # ── 엑셀 다운로드 ─────────────────────────────────────────────────────
    with col_xls:
        st.subheader("💾 결산 자료 다운로드")
        excel_bytes = create_settlement_excel(
            selected_project_name,
            total_budget,
            total_expense,
            final_balance,
            df_expenses=df_expenses,
            df_members=df_members,
        )
        st.download_button(
            label="📥 전체 결산 파일 (Excel)",
            data=excel_bytes,
            file_name=f"{selected_project_name}_최종결산.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        st.markdown("---")

    st.caption("System Version 3.5 | Powered by AI Audit & Hard Gate Security")
    
