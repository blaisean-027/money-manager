# sidebar.py
import streamlit as st
from db import run_query
from audit import log_action
# security.py에서 만든 승인 확인 함수들을 가져와야 해!
from security import is_user_approved, request_access, _render_user_approval_manager

def render_sidebar(ai_available: bool):
    """
    사이드바: 승인된 사용자만 통과시키는 출입국 심사대.
    """
    with st.sidebar:
        st.header("📂 행사(프로젝트) 센터")
        
        # 1. 관리자 모드 확인 (?mode=caesar)
        query_params = st.query_params
        is_caesar = query_params.get("mode") == "caesar"

        if is_caesar:
            # 👑 관리자(Caesar)는 무검사 통과 + 승인 관리창 오픈
            current_user = {"name": "관리자(안효현)", "student_id": "admin", "role": "admin"}
            st.sidebar.success("👑 Imperium 모드 활성")
            _render_user_approval_manager() # security.py에 만든 승인 관리창 호출
        else:
            # 🕵️ 일반 사용자: 실명 및 학번 입력 (Hard Gate)
            st.info("🔒 승인된 학우만 이용 가능합니다.")
            input_name = st.text_input("이름 (실명)")
            input_sid = st.text_input("학번", type="password") # 보안을 위해 가림

            if input_name and input_sid:
                # DB에서 승인 여부 확인 [cite: 2025-12-31]
                if is_user_approved(input_name, input_sid):
                    st.success(f"✅ 확인됨: {input_name}님")
                    current_user = {"name": input_name, "student_id": input_sid, "role": "user"}
                else:
                    # 승인되지 않았거나 대기 중인 경우
                    st.error("❌ 승인되지 않은 사용자입니다.")
                    if st.button("접속 승인 요청하기"):
                        if request_access(input_name, input_sid):
                            st.warning("요청 완료! 관리자의 승인을 기다려주세요.")
                        else:
                            st.info("이미 승인 요청 중이거나 정보가 다릅니다.")
                    st.stop() # 🛑 여기서 멈춤! 아래 코드로 못 넘어감
            else:
                st.warning("👈 왼쪽에서 이름과 학번을 입력해주세요.")
                st.stop() # 🛑 입력 전까지는 화면 봉쇄

        st.markdown("---")

        # 2. 새 행사 만들기 (승인된 사람만 여기까지 올 수 있음)
        with st.expander("➕ 새 행사 만들기"):
            new_project_name = st.text_input("행사명 (예: 2026 해오름제)")
            if st.button("행사 생성"):
                if new_project_name:
                    try:
                        run_query("INSERT INTO projects (name) VALUES (?)", (new_project_name,))
                        log_action("행사 생성", f"새 행사 '{new_project_name}' 생성됨")
                        st.success(f"'{new_project_name}' 준비 시작!")
                        st.rerun()
                    except Exception:
                        st.warning("이미 있는 이름이야.")

        # 3. 행사 목록 선택
        project_list = run_query("SELECT id, name FROM projects", fetch=True)
        if not project_list:
            st.info("👈 행사를 먼저 만들어줘!")
            st.stop()

        project_dict = {name: pid for pid, name in project_list}
        selected_project_name = st.selectbox("현재 관리 중인 행사", list(project_dict.keys()))
        current_project_id = project_dict[selected_project_name]

        st.divider()

        # 4. AI 연결 상태 표시
        if ai_available:
            st.success("🤖 AI 감사관: 연결됨")
        else:
            st.error("🤖 AI 감사관: 오프라인 (API 키 확인 필요)")

    return current_user, selected_project_name, current_project_id
