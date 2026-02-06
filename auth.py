# auth.py
import streamlit as st
import pandas as pd

from db import run_query


def get_or_login_user():
    """
    현재 로그인된 사용자 정보를 반환.
    - 이미 로그인된 경우: st.session_state["current_user"] 반환
    - 관리자 모드(mode=caesar): 관리자 사용자 반환
    - 아니면: 사이드바에서 9자리 학번 입력 받아 승인 여부 확인, 실패 시 st.stop()
    반환 형식: {"student_id": str, "name": str, "role": str}
    """
    query_params = st.query_params
    if query_params.get("mode") == "caesar":
        user = {"student_id": "000000000", "name": "관리자(본인)", "role": "admin"}
        st.session_state["current_user"] = user
        return user

    # 이미 로그인 되어 있으면 그대로 사용
    if "current_user" in st.session_state:
        return st.session_state["current_user"]

    with st.sidebar:
        st.info("🔒 승인된 학번(9자리)으로 로그인해주세요.")
        student_id = st.text_input("학번 (9자리)", max_chars=9)
        login_btn = st.button("로그인")

    if login_btn:
        if len(student_id) == 9 and student_id.isdigit():
            row = run_query(
                """
                SELECT student_id, name, role
                FROM approved_users
                WHERE student_id = ? AND active = 1
                """,
                (student_id,),
                fetch=True,
            )
            if row:
                sid, name, role = row[0]
                user = {"student_id": sid, "name": name, "role": role or "user"}
                st.session_state["current_user"] = user
                st.sidebar.success(f"{name} 학우님 환영합니다.")
                return user
            else:
                st.sidebar.error("승인되지 않은 학번이거나 비활성 상태입니다.")
        else:
            st.sidebar.error("9자리 숫자 학번을 정확히 입력해주세요.")

    # 여기까지 오면 아직 로그인 실패 → 앱 진행 중단
    st.stop()


def render_approved_user_admin():
    """
    관리자용: 승인된 학번 목록/추가/비활성화 UI.
    관리자 모드에서만 사이드바에 보여주면 된다.
    """
    with st.sidebar.expander("👮 승인된 학번 관리"):
        st.caption("관리자가 승인한 학번만 로그인이 가능합니다.")

        # 추가/업데이트
        col1, col2 = st.columns(2)
        with col1:
            new_sid = st.text_input("학번 (9자리)", key="admin_new_sid", max_chars=9)
        with col2:
            new_name = st.text_input("이름", key="admin_new_name")

        if st.button("학번 승인/업데이트"):
            if len(new_sid) == 9 and new_sid.isdigit() and new_name:
                run_query(
                    """
                    INSERT INTO approved_users (student_id, name, role, active)
                    VALUES (?, ?, 'user', 1)
                    ON CONFLICT(student_id)
                    DO UPDATE SET name=excluded.name, active=1
                    """,
                    (new_sid, new_name),
                )
                st.success("승인/업데이트 완료.")
            else:
                st.warning("9자리 학번과 이름을 모두 입력하세요.")

        # 목록
        rows = run_query(
            "SELECT student_id, name, role, active FROM approved_users ORDER BY created_at DESC",
            fetch=True,
        )
        if rows:
            df = pd.DataFrame(
                rows, columns=["학번", "이름", "역할", "활성(1=사용)"]
            )
            st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.info("아직 승인된 학번이 없습니다.")

        # 비활성화
        disable_sid = st.text_input("비활성화할 학번", key="disable_sid", max_chars=9)
        if st.button("학번 비활성화"):
            if len(disable_sid) == 9 and disable_sid.isdigit():
                run_query(
                    "UPDATE approved_users SET active = 0 WHERE student_id = ?",
                    (disable_sid,),
                )
                st.success("비활성화 완료.")
            else:
                st.warning("올바른 학번을 입력하세요.")
