import pandas as pd
import streamlit as st
from db import get_ledger


def render_ledger_tab(current_project_id: int, **kwargs):
    st.subheader("📒 통합 가계부")
    st.caption("거래일 기준 정렬 | 입력일시 = 시스템에 기록한 시각")

    df = get_ledger(current_project_id)

    if df.empty:
        st.info("아직 등록된 수입/지출 내역이 없습니다.")
        return

    # 누적 잔액 계산
    df["누적잔액"] = df["amount"].cumsum()

    # 표시용 포맷
    display = df.copy()
    display = display.rename(columns={
        "transaction_date": "거래일",
        "recorded_at":      "입력일시",
        "type":             "구분",
        "description":      "내역",
        "amount":           "금액",
        "누적잔액":          "누적잔액",
    })

    display["구분"] = display["구분"].map({"수입": "💰 수입", "지출": "💸 지출"})
    display["금액"] = display["금액"].apply(
        lambda x: f"+{x:,.0f}원" if x >= 0 else f"{x:,.0f}원"
    )
    display["누적잔액"] = display["누적잔액"].apply(
        lambda x: f"{x:,.0f}원"
    )
    display["입력일시"] = pd.to_datetime(
        display["입력일시"], errors="coerce"
    ).dt.strftime("%m/%d %H:%M")

    st.dataframe(display, use_container_width=True, hide_index=True)

    # 요약 지표
    total_income  = df[df["amount"] > 0]["amount"].sum()
    total_expense = df[df["amount"] < 0]["amount"].sum()
    balance       = total_income + total_expense

    st.divider()
    col1, col2, col3 = st.columns(3)
    col1.metric("💰 총 수입", f"{total_income:,.0f}원")
    col2.metric("💸 총 지출", f"{abs(total_expense):,.0f}원")
    col3.metric("💵 현재 잔액", f"{balance:,.0f}원")

