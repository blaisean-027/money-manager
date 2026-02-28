import datetime
import pandas as pd
import streamlit as st

from audit import log_action
from db import run_query
from accounting.service import record_income_entry

INCOME_TYPE_LABELS = {
    "school_budget": "학교/학과 지원금",
    "reserve_fund": "예비비/이월금(외부 유입)",
    "reserve_recovery": "회수/정산(예비비 복구 등)",
}

def _to_int_amount(value) -> int:
    try:
        return int(value)
    except Exception:
        return 0

def _compose_type_label(source_type: str, extra_label: str) -> str:
    base = INCOME_TYPE_LABELS.get(source_type, source_type)
    extra = (extra_label or "").strip()
    if not extra:
        return base
    return f"{base} - {extra}"

def _can_edit(current_user: dict) -> bool:
    perms = current_user.get("permissions", [])
    return "can_edit" in perms or current_user.get("role") in {"treasurer", "admin"}

def render_budget_tab(current_project_id: int, **kwargs):
    current_user = kwargs.get("current_user", {})
    can_edit = _can_edit(current_user)

    st.subheader("1️⃣ 예산/예비비 입력")
    col_budget_form, col_budget_table = st.columns([1, 2])

    with col_budget_form:
        with st.form("add_budget_entry"):
            income_date = st.date_input("입금일", datetime.date.today(), key="budget_date")
            income_type = st.selectbox(
                "수입 구분",
                ["school_budget", "reserve_fund", "reserve_recovery"],
                format_func=lambda x: INCOME_TYPE_LABELS.get(x, x),
            )
            extra_label = st.text_input(
                "추가 항목 (+알파, 선택)",
                placeholder="예: 24학번 홍길동 과잠비 / MT 회수 / 행사 후원금 등",
            )
            contributor_name = st.text_input("입금자/담당자 이름")
            amount = st.number_input("금액", min_value=0, step=1000)
            note = st.text_input("비고 (선택)")
            submit_budget = st.form_submit_button("예산 항목 등록")

        if submit_budget:
            if not contributor_name.strip():
                st.warning("입금자/담당자 이름을 입력해주세요.")
            elif amount <= 0:
                st.warning("금액은 0원보다 커야 합니다.")
            else:
                tx_date = income_date.strftime("%Y-%m-%d")
                amount_i = _to_int_amount(amount)
                run_query(
                    """
                    INSERT INTO budget_entries
                    (project_id, entry_date, source_type, contributor_name, amount, note, extra_label)
                    VALUES (:pid, :date, :type, :name, :amount, :note, :extra)
                    """,
                    {"pid": current_project_id, "date": tx_date, "type": income_type,
                     "name": contributor_name.strip(), "amount": amount_i,
                     "note": note.strip(), "extra": extra_label.strip()}
                )
                record_income_entry(
                    project_id=current_project_id, tx_date=tx_date,
                    source_type=income_type, actor_name=contributor_name.strip(),
                    amount=amount_i, note=note.strip(), extra_label=extra_label.strip(),
                )
                log_action("예산 수입 등록", f"{income_date} / {_compose_type_label(income_type, extra_label)} / {contributor_name} / {int(amount):,}원")
                st.success("예산/예비비 항목을 등록했어요.")
                st.rerun()

    with col_budget_table:
        df_budget_raw = run_query(
            """
            SELECT id, entry_date, source_type, contributor_name, amount, note, COALESCE(extra_label,'') AS extra_label
            FROM budget_entries
            WHERE project_id = :pid
            ORDER BY entry_date DESC, id DESC
            """,
            {"pid": current_project_id}, fetch=True,
        )

        if df_budget_raw is not None and not df_budget_raw.empty:
            df_budget = df_budget_raw.copy()
            df_budget["구분"] = df_budget.apply(
                lambda r: _compose_type_label(str(r["source_type"]), str(r["extra_label"])), axis=1
            )
            df_display = df_budget.rename(columns={
                "entry_date": "입금일", "contributor_name": "입금자",
                "amount": "금액", "note": "비고"
            })[["입금일", "구분", "입금자", "금액", "비고"]]
            st.dataframe(df_display, use_container_width=True, hide_index=True)

            # ── 수정/삭제 ──
            if can_edit:
                with st.expander("✏️ 예산 항목 수정/삭제"):
                    labels = [
                        f"{row['entry_date']} | {_compose_type_label(row['source_type'], row['extra_label'])} | {row['contributor_name']} | {row['amount']:,}원"
                        for _, row in df_budget_raw.iterrows()
                    ]
                    selected_idx = st.selectbox("수정할 항목 선택", range(len(labels)), format_func=lambda i: labels[i], key="budget_edit_select")
                    sel = df_budget_raw.iloc[selected_idx]

                    col_edit, col_del = st.columns([3, 1])
                    with col_edit:
                        with st.form("edit_budget_entry"):
                            e_date = st.date_input("입금일", datetime.date.fromisoformat(sel["entry_date"]))
                            e_type = st.selectbox(
                                "수입 구분",
                                ["school_budget", "reserve_fund", "reserve_recovery"],
                                index=["school_budget", "reserve_fund", "reserve_recovery"].index(sel["source_type"]) if sel["source_type"] in ["school_budget", "reserve_fund", "reserve_recovery"] else 0,
                                format_func=lambda x: INCOME_TYPE_LABELS.get(x, x),
                            )
                            e_extra = st.text_input("추가 항목", value=sel["extra_label"])
                            e_name = st.text_input("입금자", value=sel["contributor_name"])
                            e_amount = st.number_input("금액", min_value=0, step=1000, value=int(sel["amount"]))
                            e_note = st.text_input("비고", value=sel["note"] or "")
                            save_btn = st.form_submit_button("💾 수정 저장")

                        if save_btn:
                            run_query(
                                """
                                UPDATE budget_entries
                                SET entry_date=:date, source_type=:type, contributor_name=:name,
                                    amount=:amount, note=:note, extra_label=:extra
                                WHERE id=:id
                                """,
                                {"date": e_date.strftime("%Y-%m-%d"), "type": e_type,
                                 "name": e_name.strip(), "amount": int(e_amount),
                                 "note": e_note.strip(), "extra": e_extra.strip(), "id": int(sel["id"])}
                            )
                            log_action("예산 항목 수정", f"ID {sel['id']} / {e_name} / {int(e_amount):,}원")
                            st.success("수정됐어!")
                            st.rerun()

                    with col_del:
                        st.markdown("<br><br><br><br><br><br><br><br><br><br>", unsafe_allow_html=True)
                        if st.button("🗑️ 삭제", key="budget_delete_btn", type="primary"):
                            st.session_state["budget_delete_confirm"] = int(sel["id"])

                    if st.session_state.get("budget_delete_confirm") == int(sel["id"]):
                        st.warning(f"⚠️ '{sel['contributor_name']} / {sel['amount']:,}원' 정말 삭제할까?")
                        c1, c2 = st.columns(2)
                        if c1.button("✅ 확인 삭제", key="budget_delete_yes"):
                            run_query("DELETE FROM budget_entries WHERE id=:id", {"id": int(sel["id"])})
                            log_action("예산 항목 삭제", f"ID {sel['id']} / {sel['contributor_name']} / {sel['amount']:,}원")
                            st.session_state.pop("budget_delete_confirm", None)
                            st.success("삭제됐어!")
                            st.rerun()
                        if c2.button("❌ 취소", key="budget_delete_no"):
                            st.session_state.pop("budget_delete_confirm", None)
                            st.rerun()
        else:
            df_budget = pd.DataFrame(columns=["입금일", "구분", "입금자", "금액", "비고"])
            st.info("아직 등록된 예산/예비비가 없습니다.")

    st.divider()
    st.subheader("2️⃣ 학생회비 납부 기록")
    col_member_form, col_member_table = st.columns([1, 2])

    with col_member_form:
        with st.form("manual_member_payment"):
            paid_date = st.date_input("납부일", datetime.date.today(), key="member_paid_date")
            m_name = st.text_input("이름")
            m_sid = st.text_input("학번 (선택)")
            m_amt = st.number_input("납부액", min_value=0, step=1000)
            m_note = st.text_input("비고")
            submit_member = st.form_submit_button("학생회비 등록")

        if submit_member:
            if not m_name.strip():
                st.warning("이름을 입력해주세요.")
            elif m_amt <= 0:
                st.warning("납부액은 0원보다 커야 합니다.")
            else:
                tx_date = paid_date.strftime("%Y-%m-%d")
                amount_i = _to_int_amount(m_amt)
                run_query(
                    """
                    INSERT INTO members (project_id, name, student_id, deposit_amount, paid_date, note)
                    VALUES (:pid, :name, :sid, :amount, :date, :note)
                    """,
                    {"pid": current_project_id, "name": m_name.strip(), "sid": m_sid.strip(),
                     "amount": amount_i, "date": tx_date, "note": m_note.strip()}
                )
                record_income_entry(
                    project_id=current_project_id, tx_date=tx_date,
                    source_type="student_dues", actor_name=m_name.strip(),
                    amount=amount_i, note=m_note.strip(), extra_label="",
                )
                log_action("학생회비 등록", f"{paid_date} / {m_name}({m_sid}) / {int(m_amt):,}원")
                st.success("학생회비를 등록했어요.")
                st.rerun()

    with col_member_table:
        df_members_raw = run_query(
            """
            SELECT id, paid_date, name, student_id, deposit_amount, note
            FROM members
            WHERE project_id = :pid
            ORDER BY paid_date DESC, id DESC
            """,
            {"pid": current_project_id}, fetch=True,
        )

        if df_members_raw is not None and not df_members_raw.empty:
            df_members = df_members_raw.rename(columns={
                "paid_date": "납부일", "name": "이름", "student_id": "학번",
                "deposit_amount": "납부액", "note": "비고"
            })
            st.dataframe(df_members[["납부일", "이름", "학번", "납부액", "비고"]], use_container_width=True, hide_index=True)
            total_student_dues = int(df_members["납부액"].sum())

            # ── 수정/삭제 ──
            if can_edit:
                with st.expander("✏️ 학생회비 항목 수정/삭제"):
                    m_labels = [
                        f"{row['paid_date']} | {row['name']}({row['student_id'] or '-'}) | {row['deposit_amount']:,}원"
                        for _, row in df_members_raw.iterrows()
                    ]
                    m_sel_idx = st.selectbox("수정할 항목 선택", range(len(m_labels)), format_func=lambda i: m_labels[i], key="member_edit_select")
                    m_sel = df_members_raw.iloc[m_sel_idx]

                    col_medit, col_mdel = st.columns([3, 1])
                    with col_medit:
                        with st.form("edit_member_entry"):
                            me_date = st.date_input("납부일", datetime.date.fromisoformat(m_sel["paid_date"]))
                            me_name = st.text_input("이름", value=m_sel["name"])
                            me_sid = st.text_input("학번", value=m_sel["student_id"] or "")
                            me_amt = st.number_input("납부액", min_value=0, step=1000, value=int(m_sel["deposit_amount"]))
                            me_note = st.text_input("비고", value=m_sel["note"] or "")
                            m_save_btn = st.form_submit_button("💾 수정 저장")

                        if m_save_btn:
                            run_query(
                                """
                                UPDATE members
                                SET paid_date=:date, name=:name, student_id=:sid,
                                    deposit_amount=:amount, note=:note
                                WHERE id=:id
                                """,
                                {"date": me_date.strftime("%Y-%m-%d"), "name": me_name.strip(),
                                 "sid": me_sid.strip(), "amount": int(me_amt),
                                 "note": me_note.strip(), "id": int(m_sel["id"])}
                            )
                            log_action("학생회비 수정", f"ID {m_sel['id']} / {me_name} / {int(me_amt):,}원")
                            st.success("수정됐어!")
                            st.rerun()

                    with col_mdel:
                        st.markdown("<br><br><br><br><br><br><br><br><br><br>", unsafe_allow_html=True)
                        if st.button("🗑️ 삭제", key="member_delete_btn", type="primary"):
                            st.session_state["member_delete_confirm"] = int(m_sel["id"])

                    if st.session_state.get("member_delete_confirm") == int(m_sel["id"]):
                        st.warning(f"⚠️ '{m_sel['name']} / {m_sel['deposit_amount']:,}원' 정말 삭제할까?")
                        c1, c2 = st.columns(2)
                        if c1.button("✅ 확인 삭제", key="member_delete_yes"):
                            run_query("DELETE FROM members WHERE id=:id", {"id": int(m_sel["id"])})
                            log_action("학생회비 삭제", f"ID {m_sel['id']} / {m_sel['name']} / {m_sel['deposit_amount']:,}원")
                            st.session_state.pop("member_delete_confirm", None)
                            st.success("삭제됐어!")
                            st.rerun()
                        if c2.button("❌ 취소", key="member_delete_no"):
                            st.session_state.pop("member_delete_confirm", None)
                            st.rerun()
        else:
            st.info("아직 납부자가 없습니다.")
            df_members = pd.DataFrame(columns=["납부일", "이름", "학번", "납부액", "비고"])
            total_student_dues = 0

    df_school_raw = run_query(
        "SELECT COALESCE(SUM(amount), 0) AS total FROM budget_entries WHERE project_id = :pid AND source_type = 'school_budget'",
        {"pid": current_project_id}, fetch=True
    )
    school_budget_total = int(df_school_raw.iloc[0]["total"]) if (df_school_raw is not None and not df_school_raw.empty) else 0

    df_reserve_raw = run_query(
        "SELECT COALESCE(SUM(amount), 0) AS total FROM budget_entries WHERE project_id = :pid AND source_type IN ('reserve_fund','reserve_recovery')",
        {"pid": current_project_id}, fetch=True
    )
    reserve_total = int(df_reserve_raw.iloc[0]["total"]) if (df_reserve_raw is not None and not df_reserve_raw.empty) else 0

    st.markdown("### 📊 총 수입 요약")
    total_budget = school_budget_total + reserve_total + total_student_dues
    s1, s2, s3, s4 = st.columns(4)
    s1.metric("학교/학과 지원금", f"{school_budget_total:,.0f}원")
    s2.metric("예비비/회수 합계", f"{reserve_total:,.0f}원")
    s3.metric("학생회비 합계", f"{total_student_dues:,.0f}원")
    s4.metric("총 예산", f"{total_budget:,.0f}원")

    return total_budget, total_student_dues, df_members
