# export_excel.py
import io
import pandas as pd
import datetime

def create_settlement_excel(
    project_name: str,
    total_budget: int,
    total_expense: int,
    final_balance: int,
    df_expenses: pd.DataFrame = None,
    df_members: pd.DataFrame = None,
) -> bytes:
    """
    행사 결산용 엑셀 생성: 요약, 지출 상세, 납부자 명단 포함
    """
    output = io.BytesIO()
    today_str = datetime.date.today().strftime("%Y-%m-%d")
    
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        # 1. [요약 시트] 가독성을 위해 항목/내용 구조로 변경
        summary_data = [
            ["항목", "내용"],
            ["행사명", project_name],
            ["보고서 생성일", today_str],
            ["총 예산 (수입)", f"{total_budget:,}원"],
            ["총 지출", f"{total_expense:,}원"],
            ["최종 잔액", f"{final_balance:,}원"],
        ]
        pd.DataFrame(summary_data).to_excel(writer, sheet_name="회계요약", index=False, header=False)

        # 2. [지출 상세 시트]
        if df_expenses is not None and not df_expenses.empty:
            df_expenses.to_excel(writer, sheet_name="지출내역", index=False)

        # 3. [납부자 명단 시트]
        if df_members is not None and not df_members.empty:
            df_members.to_excel(writer, sheet_name="학생회비명단", index=False)

    return output.getvalue()

def create_audit_log_excel(df_logs: pd.DataFrame) -> bytes:
    """
    [신규] 감사 로그 백업용 엑셀 생성 (DB 용량 확보용)
    """
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        if df_logs is not None and not df_logs.empty:
            df_logs.to_excel(writer, sheet_name="감사로그_백업", index=False)
        else:
            pd.DataFrame([["로그 기록 없음"]]).to_excel(writer, sheet_name="감사로그_백업", index=False, header=False)
            
    return output.getvalue()
