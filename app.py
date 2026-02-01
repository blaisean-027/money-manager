import streamlit as st
import pandas as pd
import sqlite3
import datetime
import io
import google.generativeai as genai
import time
from streamlit.web.server.websocket_headers import _get_websocket_headers

# -----------------------------------------------------------------------------
# 0. 설정 및 AI 연결 (보안 강화됨!)
# -----------------------------------------------------------------------------
# [중요] 깃허브에 올릴 때 키가 노출되지 않도록 st.secrets 사용
try:
    # 스트림릿 클라우드의 Secrets 관리자에서 'GOOGLE_API_KEY'를 가져옴
    api_key = st.secrets["GOOGLE_API_KEY"]
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-1.5-flash')
    AI_AVAILABLE = True
except Exception as e:
    # 로컬에서 테스트할 때나 키가 없을 때를 대비한 예외처리
    AI_AVAILABLE = False
    # (배포 후에는 Secrets 설정이 없으면 경고가 뜰 것임)

DB_FILE = "finance_pro_v3.db"
st.set_page_config(page_title="똑똑한 과대표 AI 장부 Pro", layout="wide", page_icon="🏫")

# -----------------------------------------------------------------------------
# 🛠️ [Helper] 사용자 정보 추적 함수 (IP, 기기)
# -----------------------------------------------------------------------------
def get_user_info():
    """사용자의 IP와 기기 정보를 추출하는 함수"""
    try:
        headers = _get_websocket_headers()
        ip = headers.get("X-Forwarded-For", "Unknown IP")
        user_agent = headers.get("User-Agent", "Unknown Device")
        return ip, user_agent
    except:
        return "Unknown IP", "Unknown Device"

# -----------------------------------------------------------------------------
# 🛠️ [핵심] 감사 로그(Audit Log) 기록 함수
# -----------------------------------------------------------------------------
def log_action(action, details):
    """
    모든 중요 행동을 DB에 기록하는 CCTV 함수
    """
    query_params = st.query_params
    is_admin = query_params.get("mode") == "caesar"
    user_mode = "관리자(Caesar)" if is_admin else "일반 사용자"
    
    ip_addr, device = get_user_info()
    
    # 관리자는 '관리자'로, 일반 사용자는 입력한 실명 사용
    op_name = st.session_state.get('operator_name_input', '익명')
    if is_admin: op_name = "관리자(본인)"

    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute('''
            INSERT INTO audit_logs (action, details, user_mode, ip_address, device_info, operator_name)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (action, details, user_mode, ip_addr, device, op_name))
        conn.commit()

# -----------------------------------------------------------------------------
# 1. DB 초기화
# -----------------------------------------------------------------------------
def init_db():
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("PRAGMA foreign_keys = ON;") 
        c = conn.cursor()
        
        # 시스템 설정 & 로그 테이블
        c.execute('''CREATE TABLE IF NOT EXISTS system_config (key TEXT PRIMARY KEY, value TEXT)''')
        c.execute("INSERT OR IGNORE INTO system_config (key, value) VALUES ('status', 'NORMAL')")

        c.execute('''
            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                action TEXT,
                details TEXT,
                user_mode TEXT,
                ip_address TEXT,
                device_info TEXT,
                operator_name TEXT
            )
        ''')
        
        # 마이그레이션 (컬럼 추가)
        try: c.execute("ALTER TABLE audit_logs ADD COLUMN ip_address TEXT")
        except: pass
        try: c.execute("ALTER TABLE audit_logs ADD COLUMN device_info TEXT")
        except: pass
        try: c.execute("ALTER TABLE audit_logs ADD COLUMN operator_name TEXT")
        except: pass

        # 프로젝트, 멤버, 지출 테이블
        c.execute('''
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                school_budget INTEGER DEFAULT 0,
                carry_over_funds INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        try: c.execute("ALTER TABLE projects ADD COLUMN school_budget INTEGER DEFAULT 0")
        except: pass
        try: c.execute("ALTER TABLE projects ADD COLUMN carry_over_funds INTEGER DEFAULT 0")
        except: pass
        
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
            if fetch: return c.fetchall()
            conn.commit()
        except sqlite3.Error as e:
            st.error(f"DB 에러: {e}")
            return []

init_db()

# -----------------------------------------------------------------------------
# 2. 보안 검문소 & 관리자 기능 (루비콘)
# -----------------------------------------------------------------------------
def check_rubicon_security():
    status = run_query("SELECT value FROM system_config WHERE key = 'status'", fetch=True)[0][0]

    if status == "LOCKED":
        st.markdown("""<style>.stApp { background-color: #2c0000; color: white; }</style>""", unsafe_allow_html=True)
        st.error("🚨 Alea iacta est.")
        st.title("🏛️ 시스템 영구 봉인됨")
        unlock_code = st.text_input("해제 코드:", type="password")
        if unlock_code == "10 legio":
            with st.spinner("10군단 도착..."):
                time.sleep(2)
                run_query("UPDATE system_config SET value = 'NORMAL' WHERE key = 'status'")
                log_action("보안 해제", "시스템 잠금 해제됨 (10 legio)")
                st.rerun()
        st.stop()

    else:
        query_params = st.query_params
        secret_mode = query_params.get("mode", [None])
        
        if secret_mode == "caesar": 
            with st.sidebar.expander("⚔️ Imperium (통제권)"):
                st.info("관리자 권한 인증됨")
                kill_command = st.text_input("명령어", type="password")
                if kill_command == "루비콘":
                    st.sidebar.error("주사위를 던집니다...")
                    main_placeholder = st.empty()
                    st.markdown("""<style>img.stImage { width: 80vw !important; max-width: 800px; }</style>""", unsafe_allow_html=True)
                    main_placeholder.image("https://media.giphy.com/media/3o7TKSjRrfIPjeiVyM/giphy.gif", caption="운명 결정.")
                    time.sleep(4)
                    run_query("UPDATE system_config SET value = 'LOCKED' WHERE key = 'status'")
                    log_action("보안 잠금", "루비콘 강을 건넜습니다 (시스템 폐쇄)")
                    st.rerun()

            st.sidebar.markdown("---")
            st.sidebar.header("📜 감사 로그 센터")
            
            if st.sidebar.button("📥 로그 엑셀 백업"):
                logs = run_query("SELECT id, timestamp, action, details, user_mode, ip_address, device_info, operator_name FROM audit_logs ORDER BY id DESC", fetch=True)
                if logs:
                    df_logs = pd.DataFrame(logs, columns=['ID', '일시', '작업', '상세내용', '접속자', 'IP', '기기', '작업자명'])
                    output = io.BytesIO()
                    with pd.ExcelWriter(output, engine='openpyxl') as writer:
                        df_logs.to_excel(writer, index=False, sheet_name='감사로그')
                    st.sidebar.download_button(label="파일 저장하기", data=output.getvalue(), file_name=f"감사로그_백업_{datetime.date.today()}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                else:
                    st.sidebar.warning("기록된 로그가 없어.")

            if st.sidebar.checkbox("🗑️ 로그 기록 삭제"):
                if st.sidebar.button("정말 삭제할까?"):
                    run_query("DELETE FROM audit_logs")
                    log_action("로그 삭제", "관리자가 감사 로그를 초기화함")
                    st.sidebar.success("로그 초기화 완료!")
                    time.sleep(1)
                    st.rerun()

check_rubicon_security()

# -----------------------------------------------------------------------------
# 3. 사이드바: 실명제 강화 구역
# -----------------------------------------------------------------------------
with st.sidebar:
    st.header("📂 행사(프로젝트) 센터")
    
    # 🕵️‍♂️ [강화된 실명제 로직]
    query_params = st.query_params
    if query_params.get("mode") != "caesar":
        st.info("🔒 보안을 위해 실명을 입력해주세요.")
        
        # 이름 입력창
        op_name = st.text_input("작업자 실명 (예: 홍길동)", key="operator_name_input")
        
        # 이름이 비어있으면? -> 코드 실행 중단 (Hard Gate)
        if not op_name:
            st.warning("👈 사이드바에 이름을 입력해야 장부가 열립니다.")
            st.stop()
            
    st.markdown("---")
    
    with st.expander("➕ 새 행사 만들기"):
        new_project_name = st.text_input("행사명 (예: 2026 해오름제)")
        if st.button("행사 생성"):
            if new_project_name:
                try:
                    run_query("INSERT INTO projects (name) VALUES (?)", (new_project_name,))
                    log_action("행사 생성", f"새 행사 '{new_project_name}' 생성됨")
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
    
    # AI 연결 상태 표시
    if AI_AVAILABLE:
        st.success("🤖 AI 감사관: 연결됨")
    else:
        st.error("🤖 AI 감사관: 오프라인 (API 키 확인 필요)")

# -----------------------------------------------------------------------------
# 4. 메인 로직
# -----------------------------------------------------------------------------
st.title(f"🏫 {selected_project_name} 통합 회계 장부")

if st.query_params.get("mode") != "caesar":
    st.caption(f"👋 안녕하세요, **{st.session_state.get('operator_name_input')}** 학우님! 꼼꼼한 기록 부탁드려요.")

tab1, tab2, tab3 = st.tabs(["💰 예산 조성 (수입)", "💸 지출 내역", "📊 최종 결산 및 AI 리포트"])

# --- TAB 1: 예산 조성 ---
with tab1:
    proj_info = run_query("SELECT school_budget, carry_over_funds FROM projects WHERE id = ?", (current_project_id,), fetch=True)
    current_school_budget = proj_info[0][0] if proj_info else 0
    current_carry_over = proj_info[0][1] if proj_info else 0

    st.subheader("1️⃣ 고정 예산 (Institutional Budget)")
    with st.form("budget_source_form"):
        col_b1, col_b2 = st.columns(2)
        new_school_budget = col_b1.number_input("🏫 학교/학과 지원금", value=current_school_budget, step=10000)
        new_carry_over = col_b2.number_input("💼 전년도 이월금/예비비", value=current_carry_over, step=10000)
        
        if st.form_submit_button("고정 예산 업데이트"):
            run_query("UPDATE projects SET school_budget = ?, carry_over_funds = ? WHERE id = ?", 
                      (new_school_budget, new_carry_over, current_project_id))
            log_action("예산 수정", f"지원금: {new_school_budget}, 이월금: {new_carry_over}로 수정")
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
                if uploaded_file.name.endswith('.csv'): df_upload = pd.read_csv(uploaded_file)
                else: df_upload = pd.read_excel(uploaded_file)
                
                renamed_cols = {}
                for col in df_upload.columns:
                    if any(x in col for x in ["이름", "성명", "Name"]): renamed_cols[col] = "이름"
                    if any(x in col for x in ["금액", "입금", "Amount"]): renamed_cols[col] = "입금액"
                df_upload.rename(columns=renamed_cols, inplace=True)
                
                if "이름" in df_upload.columns and "입금액" in df_upload.columns:
                    if st.button("일괄 등록"):
                        count = 0
                        for _, row in df_upload.iterrows():
                            try: amt = int(str(row['입금액']).replace(',','').replace('원',''))
                            except: amt = 0
                            run_query("INSERT OR IGNORE INTO members (project_id, name, deposit_amount, note) VALUES (?, ?, ?, ?)",
                                      (current_project_id, row['이름'], amt, '엑셀업로드'))
                            count += 1
                        log_action("멤버 일괄 업로드", f"{count}명 데이터 엑셀로 업로드됨")
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
                    log_action("멤버 추가", f"이름: {m_name}, 금액: {m_amt}원 추가")
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

    total_budget = current_school_budget + current_carry_over + total_student_dues
    st.info(f"💰 **총 예산 합계: {total_budget:,.0f}원**")

# --- TAB 2: 지출 관리 ---
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
                log_action("지출 등록", f"{date} / {item} / {amount}원 / {category}")
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

# --- TAB 3: 결산 및 AI 정밀 감사 ---
with tab3:
    st.header("⚖️ 최종 결산 대시보드")
    total_budget = current_school_budget + current_carry_over + total_student_dues
    final_balance = total_budget - total_expense
    
    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    kpi1.metric("총 예산", f"{total_budget:,.0f}원")
    kpi2.metric("총 지출", f"{total_expense:,.0f}원")
    kpi3.metric("현재 잔액", f"{final_balance:,.0f}원")
    usage_rate = (total_expense / total_budget * 100) if total_budget > 0 else 0
    kpi4.metric("예산 소진율", f"{usage_rate:.1f}%")

    st.subheader("📊 재정 시각화 리포트")
    col_v1, col_v2 = st.columns(2)
    
    with col_v1:
        st.write("📂 **분류별 지출 비중**")
        if 'df_expenses' in locals() and not df_expenses.empty:
            chart_data = df_expenses.groupby('분류')['금액'].sum()
            st.bar_chart(chart_data, color="#ff4b4b") 
        else:
            st.info("지출 내역이 입력되면 차트가 나타나.")

    with col_v2:
        st.write("📈 **예산 대비 지출 현황**")
        compare_df = pd.DataFrame({
            "항목": ["총 예산", "총 지출"],
            "금액": [total_budget, total_expense]
        }).set_index("항목")
        st.bar_chart(compare_df, color="#4b86ff")

    st.write(f"📉 **전체 예산 집행률 ({usage_rate:.1f}%)**")
    progress_val = min(usage_rate / 100, 1.0)
    st.progress(progress_val)

    st.divider()
    col_ai, col_xls = st.columns([2, 1])

    with col_ai:
        st.subheader("🤖 AI 총무 정밀 감사 & 분석")
        
        if AI_AVAILABLE:
            if st.button("🚨 AI 장부 정밀 감사 실행"):
                with st.spinner("125명 국제학부 재정 데이터를 AI가 정밀 분석 중..."):
                    # 1. 지출 내역 요약 (텍스트로 변환)
                    exp_summary = df_expenses.to_string() if 'df_expenses' in locals() and not df_expenses.empty else "지출 내역 없음"
                    
                    # 2. 강력한 프롬프트: 분석 결과와 시각화 점수를 분리해서 요청
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
                    
                    try:
                        response = model.generate_content(prompt)
                        full_text = response.text
                        
                        # 3. 결과 파싱 (리포트와 점수 분리)
                        report_part = full_text.split("[SCORES]")[0].replace("[REPORT]", "")
                        score_part = full_text.split("[SCORES]")[1] if "[SCORES]" in full_text else ""
                        
                        st.session_state['ai_audit_report'] = report_part
                        
                        # 4. 차트 데이터 생성
                        if score_part:
                            s_dict = {k.strip(): int(v.strip()) for k, v in [i.split(':') for i in score_part.split(',')]}
                            st.session_state['ai_risk_chart'] = pd.DataFrame(list(s_dict.items()), columns=['항목', '위험 점수'])
                            
                        log_action("AI 정밀 감사", "AI 감사관이 리포트와 위험도 차트를 생성함")
                        st.success("감사 완료! 아래 결과를 확인하세요.")
                        
                    except Exception as e:
                        st.error(f"분석 중 오류 발생: {e}")

            # 5. 결과 화면 출력
            if 'ai_audit_report' in st.session_state:
                st.info("📑 AI 감사 보고서")
                st.markdown(st.session_state['ai_audit_report'])
                
                if 'ai_risk_chart' in st.session_state:
                    st.write("📊 **AI 선정 지출 위험도 분석** (높을수록 정밀 조사 필요)")
                    st.bar_chart(st.session_state['ai_risk_chart'].set_index('항목'), color="#d33682")
        else:
            st.warning("⚠️ AI 기능이 꺼져있어. (API 키 설정 필요)")

    with col_xls:
        st.subheader("💾 결산 자료 다운로드")
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            summary_data = [
                ["구분", "항목", "금액"],
                ["수입", "총 예산", total_budget],
                ["지출", "총 지출", total_expense],
                ["결과", "잔액", final_balance]
            ]
            pd.DataFrame(summary_data[1:], columns=summary_data[0]).to_excel(writer, sheet_name='요약', index=False)
            if 'df_expenses' in locals(): df_expenses.to_excel(writer, sheet_name='지출', index=False)
            if 'df_members' in locals(): df_members.to_excel(writer, sheet_name='명단', index=False)

        st.download_button(
            label="📥 전체 결산 파일 (Excel)",
            data=output.getvalue(),
            file_name=f"{selected_project_name}_최종결산.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        
        query_params = st.query_params
        if query_params.get("mode") == "caesar":
             st.info("💡 감사 로그 다운로드는 왼쪽 사이드바 '감사 로그 센터'를 이용해줘!")

st.markdown("---")
st.caption("System Version 3.4 | Powered by Gemini AI Audit & Hard Gate Security")