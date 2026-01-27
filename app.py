import streamlit as st
import pandas as pd
import sqlite3
import datetime
import io
import google.generativeai as genai
import time
# -----------------------------------------------------------------------------
# 0. 설정 및 비밀키 (보안 중요!)
# -----------------------------------------------------------------------------
# [중요] 여기에 네가 발급받은 Gemini API 키를 넣어줘!
GOOGLE_API_KEY = 'AIzaSyCe9grvudKeA2bsQa1eszvgnqi_9fiMfqM'
# 제미나이 설정 (오류나면 AI 없이 돌아가도록 예외처리 함)
try:
    genai.configure(api_key=GOOGLE_API_KEY)
    model = genai.GenerativeModel('gemini-1.5-flash')
    AI_AVAILABLE = True
except Exception:
    AI_AVAILABLE = False

DB_FILE = "finance_pro_v3.db" # DB 버전 업데이트
st.set_page_config(page_title="똑똑한 과대표 AI 장부 Pro", layout="wide", page_icon="🏫")
# ==============================================
# 🕵️‍♂️ [최종] 시크릿 URL 기반 루비콘 보안 시스템
# ==============================================

# 1. DB 초기화 및 상태 관리 (동일함)
def init_security_db():
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS system_config (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        ''')
        c.execute("INSERT OR IGNORE INTO system_config (key, value) VALUES ('status', 'NORMAL')")
        conn.commit()

def set_system_status(status):
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute("UPDATE system_config SET value = ? WHERE key = 'status'", (status,))
        conn.commit()

def get_system_status():
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute("SELECT value FROM system_config WHERE key = 'status'")
        result = c.fetchone()
        return result[0] if result else "NORMAL"

# 2. 보안 검문소 (여기가 핵심!)
def check_rubicon_security():
    init_security_db()
    status = get_system_status()

    # 🔒 [상황 A] 이미 잠긴 상태 (여긴 학생들도 봐야 함 - 그래야 잠긴 걸 아니까)
    if status == "LOCKED":
        st.markdown("""
            <style> .stApp { background-color: #2c0000; color: white; } </style>
        """, unsafe_allow_html=True)
        st.error("🚨 Alea iacta est.")
        st.title("🏛️ 시스템 영구 봉인됨")
        
        # 해제 코드 입력창은 잠긴 상태에서는 보여줘도 됨 (어차피 못 푸니까)
        unlock_code = st.text_input("해제 코드:", type="password")
        if unlock_code == "10 legio":
            with st.spinner("10군단 도착..."):
                time.sleep(2)
                set_system_status("NORMAL")
                st.rerun()
        st.stop()

    # 🔓 [상황 B] 평화로운 상태 (학생들에게는 깨끗한 화면만!)
    else:
        # URL 주소창에 '?mode=caesar'가 있는지 몰래 확인
        # 예: http://localhost:8501/?mode=caesar
        query_params = st.query_params
        secret_mode = query_params.get("mode", [None])
        
        # 만약 주소 뒤에 비밀 암호가 붙어 있다면? -> 기폭 장치 노출
        if secret_mode == "caesar": 
            with st.sidebar.expander("⚔️ Imperium (관리자 전용)"):
                st.info("관리자 모드로 접속했습니다.")
                kill_command = st.text_input("명령어", type="password")
                
                if kill_command == "루비콘":
                    st.sidebar.error("주사위를 던집니다...")
                    
                    # 전체 화면 주사위 연출
                    main_placeholder = st.empty()
                    st.markdown("""
                        <style>
                        .main .block-container { max-width: 95% !important; padding-top: 2rem !important; text-align: center; }
                        img.stImage { width: 80vw !important; max-width: 800px; border-radius: 20px; box-shadow: 0 0 50px red; }
                        </style>
                    """, unsafe_allow_html=True)

                    dice_url = "https://media.giphy.com/media/3o7TKSjRrfIPjeiVyM/giphy.gif"
                    main_placeholder.image(dice_url, caption="운명이 결정되었습니다.")
                    
                    time.sleep(4)
                    set_system_status("LOCKED")
                    st.rerun()
        
        # 비밀 암호가 없으면? -> 아무것도 안 함 (학생들은 여기 코드가 있는지도 모름)
        else:
            pass 

# 실행
check_rubicon_security()
# -----------------------------------------------------------------------------
# 1. 고난이도 DB 로직 (스키마 마이그레이션 포함)
# -----------------------------------------------------------------------------
def init_db():
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("PRAGMA foreign_keys = ON;") 
        c = conn.cursor()
        
        # 프로젝트 테이블 (예산 컬럼 추가)
        c.execute('''
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                school_budget INTEGER DEFAULT 0,
                carry_over_funds INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # 기존 테이블에 컬럼이 없을 경우를 대비한 마이그레이션 (DB파일 유지 시)
        try:
            c.execute("ALTER TABLE projects ADD COLUMN school_budget INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass # 이미 있음
        try:
            c.execute("ALTER TABLE projects ADD COLUMN carry_over_funds INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass # 이미 있음
        
        # 멤버 테이블
        c.execute('''
            CREATE TABLE IF NOT EXISTS members (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER,
                name TEXT NOT NULL,
                deposit_amount INTEGER DEFAULT 0,
                note TEXT,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
                UNIQUE(project_id, name)
            )
        ''')
        
        # 지출 테이블
        c.execute('''
            CREATE TABLE IF NOT EXISTS expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER,
                date TEXT,
                item TEXT,
                amount INTEGER,
                category TEXT,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
            )
        ''')
        conn.commit()

def run_query(query, params=(), fetch=False):
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("PRAGMA foreign_keys = ON;")
        c = conn.cursor()
        try:
            c.execute(query, params)
            if fetch:
                return c.fetchall()
            conn.commit()
        except sqlite3.Error as e:
            st.error(f"DB 에러 발생: {e}")
            return []

# 초기화 실행
init_db()

# -----------------------------------------------------------------------------
# 2. 사이드바: 프로젝트 관리
# -----------------------------------------------------------------------------
with st.sidebar:
    st.header("📂 행사(프로젝트) 센터")
    
    with st.expander("➕ 새 행사 만들기"):
        new_project_name = st.text_input("행사명 (예: 2026 해오름제)")
        if st.button("행사 생성"):
            if new_project_name:
                try:
                    run_query("INSERT INTO projects (name) VALUES (?)", (new_project_name,))
                    st.success(f"'{new_project_name}' 준비 시작!")
                    st.rerun()
                except:
                    st.warning("이미 있는 이름이야.")
    
    project_list = run_query("SELECT id, name FROM projects", fetch=True)
    
    if not project_list:
        st.info("👈 행사를 먼저 만들어줘!")
        st.stop()

    project_dict = {name: pid for pid, name in project_list}
    selected_project_name = st.selectbox("현재 관리 중인 행사", list(project_dict.keys()))
    current_project_id = project_dict[selected_project_name]
    
    st.divider()
    st.caption(f"🤖 AI 상태: {'🟢 연결됨' if AI_AVAILABLE else '🔴 오프라인'}")

# -----------------------------------------------------------------------------
# 3. 메인 로직
# -----------------------------------------------------------------------------
st.title(f"🏫 {selected_project_name} 통합 회계 장부")

# 탭 구조 변경: 예산 소스 관리를 명확하게 분리
tab1, tab2, tab3 = st.tabs(["💰 예산 조성 (수입)", "💸 지출 내역", "📊 최종 결산 및 리포트"])

# --- TAB 1: 예산 조성 (3가지 소스 관리) ---
with tab1:
    # 현재 프로젝트의 고정 예산 정보 가져오기
    proj_info = run_query("SELECT school_budget, carry_over_funds FROM projects WHERE id = ?", (current_project_id,), fetch=True)
    current_school_budget = proj_info[0][0] if proj_info else 0
    current_carry_over = proj_info[0][1] if proj_info else 0

    st.subheader("1️⃣ 고정 예산 (Institutional Budget)")
    with st.form("budget_source_form"):
        col_b1, col_b2 = st.columns(2)
        with col_b1:
            new_school_budget = st.number_input("🏫 학교/학과 지원금", value=current_school_budget, step=10000)
        with col_b2:
            new_carry_over = st.number_input("💼 전년도 이월금/예비비", value=current_carry_over, step=10000)
        
        if st.form_submit_button("고정 예산 업데이트"):
            run_query("UPDATE projects SET school_budget = ?, carry_over_funds = ? WHERE id = ?", 
                      (new_school_budget, new_carry_over, current_project_id))
            st.success("예산 정보가 수정됐어!")
            st.rerun()

    st.divider()

    st.subheader("2️⃣ 학생회비 납부 (Student Dues)")
    col_m1, col_m2 = st.columns([1, 2])
    
    with col_m1:
        st.caption("엑셀 업로드 또는 수동 입력")
        uploaded_file = st.file_uploader("명단 파일(xlsx/csv)", type=['xlsx', 'csv'])
        if uploaded_file:
            try:
                if uploaded_file.name.endswith('.csv'):
                    df_upload = pd.read_csv(uploaded_file)
                else:
                    df_upload = pd.read_excel(uploaded_file)
                
                # 컬럼 유연성 처리
                renamed_cols = {}
                for col in df_upload.columns:
                    if any(x in col for x in ["이름", "성명", "Name"]): renamed_cols[col] = "이름"
                    if any(x in col for x in ["금액", "입금", "Amount"]): renamed_cols[col] = "입금액"
                df_upload.rename(columns=renamed_cols, inplace=True)
                
                if "이름" in df_upload.columns and "입금액" in df_upload.columns:
                    if st.button("일괄 등록"):
                        for _, row in df_upload.iterrows():
                            try: amt = int(str(row['입금액']).replace(',','').replace('원',''))
                            except: amt = 0
                            run_query("INSERT OR IGNORE INTO members (project_id, name, deposit_amount, note) VALUES (?, ?, ?, ?)",
                                      (current_project_id, row['이름'], amt, '엑셀업로드'))
                        st.success("업로드 완료!")
                        st.rerun()
                else:
                    st.error("컬럼명을 확인해줘 (이름, 입금액)")
            except Exception as e:
                st.error(f"에러: {e}")

        with st.expander("수동 추가"):
            with st.form("manual_mem"):
                m_name = st.text_input("이름")
                m_amt = st.number_input("납부액", step=1000)
                if st.form_submit_button("추가"):
                    run_query("INSERT INTO members (project_id, name, deposit_amount) VALUES (?, ?, ?)", (current_project_id, m_name, m_amt))
                    st.rerun()

    with col_m2:
        members_data = run_query("SELECT id, name, deposit_amount FROM members WHERE project_id = ?", (current_project_id,), fetch=True)
        if members_data:
            df_members = pd.DataFrame(members_data, columns=['ID', '이름', '납부액'])
            st.dataframe(df_members, use_container_width=True, hide_index=True)
            total_student_dues = df_members['납부액'].sum()
        else:
            st.info("아직 납부자가 없어.")
            total_student_dues = 0

    # 총 예산 요약 박스
    total_budget = current_school_budget + current_carry_over + total_student_dues
    st.info(f"""
    💰 **총 예산 합계: {total_budget:,.0f}원** (학교지원금: {current_school_budget:,.0f} + 이월금: {current_carry_over:,.0f} + 학생회비: {total_student_dues:,.0f})
    """)

# --- TAB 2: 지출 관리 (기존 유지) ---
with tab2:
    col_e1, col_e2 = st.columns([1, 2])
    with col_e1:
        st.subheader("💳 지출 기록")
        with st.form("add_expense"):
            date = st.date_input("날짜", datetime.date.today())
            item = st.text_input("내역 (예: OT 대관료)")
            category = st.selectbox("분류", ["식비/간식", "회식비", "장소대관", "물품구매", "홍보비", "교통비", "기타"])
            amount = st.number_input("금액", step=100)
            if st.form_submit_button("지출 등록"):
                run_query("INSERT INTO expenses (project_id, date, item, amount, category) VALUES (?, ?, ?, ?, ?)",
                          (current_project_id, date, item, amount, category))
                st.rerun()
                
    with col_e2:
        st.subheader("📋 지출 내역")
        expenses_data = run_query("SELECT date, category, item, amount FROM expenses WHERE project_id = ? ORDER BY date DESC", (current_project_id,), fetch=True)
        if expenses_data:
            df_expenses = pd.DataFrame(expenses_data, columns=['날짜', '분류', '내역', '금액'])
            st.dataframe(df_expenses, use_container_width=True, hide_index=True)
            total_expense = df_expenses['금액'].sum()
            st.error(f"💸 총 지출: {total_expense:,.0f}원")
        else:
            total_expense = 0
            st.info("지출 내역이 없어.")

# --- TAB 3: 결산 및 리포트 (핵심 고도화) ---
with tab3:
    st.header("⚖️ 최종 결산 대시보드")
    
    # 1. 핵심 데이터 계산
    # 수입 (Tab 1에서 계산된 변수들 재활용을 위해 다시 조회하거나 위에서 계산된 값 사용)
    # 여기서는 안전하게 다시 정리
    total_budget = current_school_budget + current_carry_over + total_student_dues
    
    # 잔액 계산
    final_balance = total_budget - total_expense
    
    # 2. 메인 대시보드 (KPI)
    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    kpi1.metric("총 예산 (수입)", f"{total_budget:,.0f}원")
    kpi2.metric("총 지출", f"{total_expense:,.0f}원")
    kpi3.metric("현재 잔액", f"{final_balance:,.0f}원", delta_color="normal")
    
    # 예산 집행률
    usage_rate = (total_expense / total_budget * 100) if total_budget > 0 else 0
    kpi4.metric("예산 소진율", f"{usage_rate:.1f}%")

    st.divider()

    col_ai, col_xls = st.columns([2, 1])

    with col_ai:
        st.subheader("🤖 AI 총무 리포트")
        if AI_AVAILABLE:
            if st.button("AI 분석 실행"):
                with st.spinner("장부 분석 중..."):
                    summary_text = f"""
                    행사명: {selected_project_name}
                    [수입 구조]
                    - 학교 지원금: {current_school_budget}원
                    - 이월금: {current_carry_over}원
                    - 학생회비 총액: {total_student_dues}원
                    - 총 예산: {total_budget}원
                    
                    [지출 현황]
                    - 총 지출: {total_expense}원
                    - 잔액: {final_balance}원
                    """
                    
                    prompt = f"""
                    당신은 대학교 학과 학생회의 '수석 총무'입니다. 
                    이번 행사의 재정 상태를 분석해서 보고서를 써주세요.
                    
                    1. **수입/지출 요약**: 예산이 어디서 얼마나 들어왔고, 얼마나 썼는지 간략히.
                    2. **잔액 평가**: 남은 돈({final_balance}원)이 적절한지, 너무 많이 남았으면 "다음 행사에 보태 쓰자"고 하고, 부족하면 "아껴 써야 했다"고 코멘트.
                    3. **조언**: 학생회비 의존도가 높은지, 학교 지원금을 잘 활용했는지 평가.
                    4. **말투**: 꼼꼼하지만 후배들을 잘 챙기는 선배 느낌.
                    
                    데이터: {summary_text}
                    """
                    response = model.generate_content(prompt)
                    st.session_state['ai_report_v3'] = response.text
                    st.success("작성 완료!")
            
            if 'ai_report_v3' in st.session_state:
                st.markdown(st.session_state['ai_report_v3'])
        else:
            st.warning("API 키가 없어서 AI가 쉬고 있어.")

    with col_xls:
        st.subheader("💾 결산 자료 다운로드")
        
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            # Sheet 1: 회계 요약 보고서 (커스텀 데이터프레임)
            summary_data = [
                ["구분", "항목", "금액", "비고"],
                ["수입", "1. 학교/학과 지원금", current_school_budget, "고정 예산"],
                ["수입", "2. 전년도 이월금", current_carry_over, "초기 자금"],
                ["수입", "3. 학생회비 합계", total_student_dues, f"{len(df_members) if 'df_members' in locals() else 0}명 납부"],
                ["수입", "[총 예산 합계]", total_budget, ""],
                ["지출", "[총 지출 합계]", total_expense, ""],
                ["결과", "[최종 잔액]", final_balance, "차기 이월 예정"]
            ]
            df_summary = pd.DataFrame(summary_data[1:], columns=summary_data[0])
            df_summary.to_excel(writer, sheet_name='회계요약', index=False)
            
            # Sheet 2: 지출 상세
            if 'df_expenses' in locals() and not df_expenses.empty:
                df_expenses.to_excel(writer, sheet_name='지출상세내역', index=False)
            else:
                pd.DataFrame(["지출 내역 없음"]).to_excel(writer, sheet_name='지출상세내역')
                
            # Sheet 3: 납부자 명단 (학생회비 납부 확인용)
            if 'df_members' in locals() and not df_members.empty:
                # 납부 여부 표시 (0원 초과면 납부)
                df_mem_xls = df_members.copy()
                df_mem_xls['상태'] = df_mem_xls['납부액'].apply(lambda x: '완납' if x > 0 else '미납')
                df_mem_xls.to_excel(writer, sheet_name='납부자명단', index=False)
            else:
                pd.DataFrame(["납부자 없음"]).to_excel(writer, sheet_name='납부자명단')

        st.download_button(
            label="📥 전체 결산 파일 (Excel)",
            data=output.getvalue(),
            file_name=f"{selected_project_name}_최종결산.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

# -----------------------------------------------------------------------------
# 4. 마무리
# -----------------------------------------------------------------------------
st.markdown("---")
st.caption("System Version 3.0 | Multi-Source Budget Management System")