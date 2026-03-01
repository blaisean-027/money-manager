import datetime
import os
import uuid

import pandas as pd
import streamlit as st
from audit import log_action
from db import run_query
from accounting.service import record_expense_entry
from ai_audit import parse_receipt_image

UPLOAD_DIR = "uploads"
CATEGORIES = [
    "식비/간식", "회식비", "장소대관",
    "물품구매", "홍보비", "교통비",
    "기타", "과잠 제작비(예비비 선지출)",
]

def _can_upload(current_user: dict) -> bool:
    perms = current_user.get("permissions", [])
    return "can_upload_receipt" in perms or current_user.get("role") in {"treasurer", "admin"}

def _can_edit(current_user: dict) -> bool:
    perms = current_user.get("permissions", [])
    return "can_edit" in perms or current_user.get("role") in {"treasurer", "admin"}

def _save_image(project_id: int, file) -> tuple[str, str]:
    folder = os.path.join(UPLOAD_DIR, f"project_{project_id}")
    os.makedirs(folder, exist_ok=True)
    ext = os.path.splitext(file.name)[-1].lower() or ".jpg"
    filename = f"{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}{ext}"
    filepath = os.path.join(folder, filename)
    with open(filepath, "wb") as f:
        f.write(file.getbuffer())
    return filename, filepath

def _register_image(project_id, expense_id, filename, filepath, description, uploaded_by):
    run_query(
        """
        INSERT INTO receipt_images
        (project_id, expense_id, filename, filepath, description, uploaded_by)
        VALUES (:pid, :eid, :fname, :fpath, :desc, :user)
        """,
        {"pid": project_id, "eid": expense_id, "fname": filename,
         "fpath": filepath, "desc": description, "user": uploaded_by}
    )

def render_expense_tab(current_project_id: int, current_user: dict = None):
    current_user = current_user or {}
    can_upload = _can_upload(current_user)
    can_edit = _can_edit(current_user)
    operator = current_user.get("name", st.session_state.get("operator_name_input", "익명"))
    ai_client = st.session_state.get("ai_client")

    tab_input, tab_gallery = st.tabs(["💳 지출 등록", "🖼️ 이미지 갤러리"])

    with tab_input:
        col_e1, col_e2 = st.columns([1, 2])

        with col_e1:
            st.subheader("💳 지출 기록")
            parsed = {}
            uploaded_file = None

            if can_upload:
                st.markdown("**🧾 영수증 첨부 (선택)**")
                uploaded_file = st.file_uploader(
                    "이미지 업로드 (jpg/png/webp)",
                    type=["jpg", "jpeg", "png", "webp"],
                    key=f"receipt_upload_{current_project_id}",
                )
                if uploaded_file:
                    st.image(uploaded_file, caption="첨부 이미지 미리보기", use_container_width=True)
                    if ai_client and st.button("🤖 AI로 영수증 자동 읽기", key="parse_receipt_btn"):
                        with st.spinner("AI가 영수증을 읽는 중..."):
                            try:
                                mime = "image/jpeg"
                                if uploaded_file.name.endswith(".png"):
                                    mime = "image/png"
                                elif uploaded_file.name.endswith(".webp"):
                                    mime = "image/webp"
                                parsed = parse_receipt_image(ai_client, uploaded_file.getvalue(), mime)
                                st.session_state["parsed_receipt"] = parsed
                                st.success("✅ AI 파싱 완료! 아래 내용을 확인 후 수정하세요.")
                            except Exception as e:
                                if "429" in str(e) or "quota" in str(e).lower():
                                    st.warning("⏳ AI 요청이 너무 많습니다. 잠시 후 다시 시도하세요.")
                                else:
                                    st.error(f"파싱 오류: {e}")
                    elif not ai_client:
                        st.caption("💡 영수증 내용을 아래 양식에 직접 입력해주세요.")
            else:
                st.caption("🔒 영수증 첨부 권한이 없습니다.")

            parsed = st.session_state.get("parsed_receipt", {})
            st.markdown("---")

            with st.form("add_expense"):
                default_date = datetime.date.today()
                if parsed.get("date"):
                    try:
                        default_date = datetime.date.fromisoformat(parsed["date"])
                    except Exception:
                        pass
                date = st.date_input("실제 지출일", value=default_date)
                item = st.text_input("지출 항목/내역", value=parsed.get("item", ""))
                category_idx = CATEGORIES.index(parsed["category"]) if parsed.get("category") in CATEGORIES else 0
                category = st.selectbox("분류", CATEGORIES, index=category_idx)
                amount = st.number_input("지출 금액", min_value=0, step=100, value=int(parsed.get("amount", 0)))
                description = st.text_area(
                    "이미지 설명 (선택)",
                    value=parsed.get("raw_text", "")[:200] if parsed.get("raw_text") else "",
                    placeholder="영수증 내용 또는 첨부 이미지에 대한 메모",
                    height=80,
                )
                submit = st.form_submit_button("✅ 지출 등록")

            if submit:
                if not item.strip():
                    st.warning("지출 항목/내역을 입력해주세요.")
                elif amount <= 0:
                    st.warning("지출 금액은 0원보다 커야 합니다.")
                else:
                    tx_date = date.strftime("%Y-%m-%d")
                    amount_i = int(amount)
                    # 💡 애저(MS SQL) 용 문법 + run_query(fetch=True)로 ID 수집
                    df_inserted = run_query(
                        """
                        INSERT INTO expenses (project_id, date, item, amount, category)
                        OUTPUT INSERTED.id
                        VALUES (:pid, :date, :item, :amount, :cat)
                        """,
                        {
                            "pid": current_project_id,
                            "date": tx_date,
                            "item": item.strip(),
                            "amount": amount_i,
                            "cat": category,
                        },
                        fetch=True,
                    )
                    expense_id = int(df_inserted.iloc[0]["id"]) if (df_inserted is not None and not df_inserted.empty) else None
                    if uploaded_file and can_upload:
                        filename, filepath = _save_image(current_project_id, uploaded_file)
                        _register_image(current_project_id, expense_id, filename, filepath, description.strip(), operator)
                    record_expense_entry(
                        project_id=current_project_id, tx_date=tx_date,
                        category=category, item=item.strip(),
                        amount=amount_i, actor_name=operator,
                    )
                    log_action("지출 등록", f"{tx_date} / {item} / {amount_i:,}원 / {category}")
                    st.session_state.pop("parsed_receipt", None)
                    st.success("✅ 지출이 등록되었습니다.")
                    st.rerun()

        with col_e2:
            st.subheader("📋 지출 내역")
            df_expenses_raw = run_query(
                """
                SELECT e.id, e.date, e.category, e.item, e.amount,
                CASE WHEN r.id IS NOT NULL THEN '🧾' ELSE '' END AS 영수증
                FROM expenses e
                LEFT JOIN receipt_images r ON r.expense_id = e.id
                WHERE e.project_id = :pid
                ORDER BY e.date DESC, e.id DESC
                """,
                {"pid": current_project_id}, fetch=True,
            )

            if df_expenses_raw is not None and not df_expenses_raw.empty:
                df_expenses = df_expenses_raw.rename(columns={
                    "date": "날짜", "category": "분류", "item": "내역", "amount": "금액"
                })
                st.dataframe(df_expenses[["날짜", "분류", "내역", "금액", "영수증"]], use_container_width=True, hide_index=True)
                total_expense = int(df_expenses["금액"].sum())
                st.error(f"💸 총 지출: {total_expense:,.0f}원")

                # ── 수정/삭제 ──
                if can_edit:
                    with st.expander("✏️ 지출 항목 수정/삭제"):
                        e_labels = [
                            f"{row['date']} | {row['category']} | {row['item']} | {row['amount']:,}원"
                            for _, row in df_expenses_raw.iterrows()
                        ]
                        e_sel_idx = st.selectbox("수정할 항목 선택", range(len(e_labels)), format_func=lambda i: e_labels[i], key="expense_edit_select")
                        e_sel = df_expenses_raw.iloc[e_sel_idx]

                        col_eedit, col_edel = st.columns([3, 1])
                        with col_eedit:
                            with st.form("edit_expense_entry"):
                                ee_date = st.date_input("지출일", datetime.date.fromisoformat(e_sel["date"]))
                                ee_item = st.text_input("항목/내역", value=e_sel["item"])
                                ee_cat_idx = CATEGORIES.index(e_sel["category"]) if e_sel["category"] in CATEGORIES else 0
                                ee_cat = st.selectbox("분류", CATEGORIES, index=ee_cat_idx)
                                ee_amt = st.number_input("금액", min_value=0, step=100, value=int(e_sel["amount"]))
                                e_save_btn = st.form_submit_button("💾 수정 저장")

                            if e_save_btn:
                                run_query(
                                    """
                                    UPDATE expenses
                                    SET date=:date, item=:item, category=:cat, amount=:amount
                                    WHERE id=:id
                                    """,
                                    {"date": ee_date.strftime("%Y-%m-%d"), "item": ee_item.strip(),
                                     "cat": ee_cat, "amount": int(ee_amt), "id": int(e_sel["id"])}
                                )
                                log_action("지출 항목 수정", f"ID {e_sel['id']} / {ee_item} / {int(ee_amt):,}원")
                                st.success("수정됐어!")
                                st.rerun()

                        with col_edel:
                            st.markdown("<br><br><br><br><br><br><br><br><br><br>", unsafe_allow_html=True)
                            if st.button("🗑️ 삭제", key="expense_delete_btn", type="primary"):
                                st.session_state["expense_delete_confirm"] = int(e_sel["id"])

                        if st.session_state.get("expense_delete_confirm") == int(e_sel["id"]):
                            st.warning(f"⚠️ '{e_sel['item']} / {e_sel['amount']:,}원' 정말 삭제할까?")
                            c1, c2 = st.columns(2)
                            if c1.button("✅ 확인 삭제", key="expense_delete_yes"):
                                run_query("DELETE FROM expenses WHERE id=:id", {"id": int(e_sel["id"])})
                                log_action("지출 항목 삭제", f"ID {e_sel['id']} / {e_sel['item']} / {e_sel['amount']:,}원")
                                st.session_state.pop("expense_delete_confirm", None)
                                st.success("삭제됐어!")
                                st.rerun()
                            if c2.button("❌ 취소", key="expense_delete_no"):
                                st.session_state.pop("expense_delete_confirm", None)
                                st.rerun()
            else:
                df_expenses = pd.DataFrame(columns=["날짜", "분류", "내역", "금액", "영수증"])
                total_expense = 0
                st.info("지출 내역이 없습니다.")

    with tab_gallery:
        st.subheader("🖼️ 프로젝트 이미지 갤러리")
        df_images = run_query(
            """
            SELECT r.id, r.filename, r.filepath, r.description,
            r.uploaded_by, r.uploaded_at, e.item, e.amount, e.date
            FROM receipt_images r
            LEFT JOIN expenses e ON e.id = r.expense_id
            WHERE r.project_id = :pid
            ORDER BY r.uploaded_at DESC
            """,
            {"pid": current_project_id}, fetch=True,
        )
        if df_images is None or df_images.empty:
            st.info("첨부된 이미지가 없습니다.")
        else:
            cols = st.columns(3)
            for idx, row in df_images.iterrows():
                img_id = row["id"]
                filepath = row["filepath"]
                desc = row["description"]
                uploader = row["uploaded_by"]
                with cols[idx % 3]:
                    if os.path.exists(filepath):
                        st.image(filepath, use_container_width=True)
                    else:
                        st.warning(f"파일 없음: {row['filename']}")
                    if row["item"]:
                        st.caption(f"📎 {row['date']} | {row['item']} | {row['amount']:,}원")
                    st.caption(f"📝 {desc or '설명 없음'}")
                    st.caption(f"👤 {uploader} | {str(row['uploaded_at'])[:16]}")
                    current_name = current_user.get("name", "")
                    if current_user.get("role") in {"treasurer", "admin"} or current_name == uploader:
                        with st.expander("✏️ 설명 수정"):
                            new_desc = st.text_area("새 설명", value=desc or "", key=f"desc_{img_id}")
                            if st.button("저장", key=f"save_desc_{img_id}"):
                                run_query("UPDATE receipt_images SET description=:desc WHERE id=:id",
                                          {"desc": new_desc.strip(), "id": img_id})
                                st.rerun()

    df_return = df_expenses[["날짜", "분류", "내역", "금액"]] if "영수증" in df_expenses.columns else df_expenses
    return total_expense, df_return
