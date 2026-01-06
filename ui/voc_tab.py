import streamlit as st

from ui.ui_helper import get_http_client, ui_lock, ui_unlock, scroll_to_bottom


def render_voc_tab(backend_url: str) -> None:
    # ---------- state init ----------
    if "voc_messages" not in st.session_state:
        st.session_state.voc_messages = []
    if "voc_status" not in st.session_state:
        st.session_state.voc_status = "idle"  # idle | queued | calling
    if "voc_pending_message" not in st.session_state:
        st.session_state.voc_pending_message = None
    if "voc_scroll_pending" not in st.session_state:
        st.session_state.voc_scroll_pending = False

    is_busy = st.session_state.voc_status in ("queued", "calling")

    # idle이면 잠금 흔적 해제(안전장치)
    if not is_busy:
        ui_unlock()

    # ---------- phase: calling (백엔드 호출) ----------
    if st.session_state.voc_status == "calling" and st.session_state.voc_pending_message:
        msg = st.session_state.voc_pending_message

        try:
            client = get_http_client(timeout=240)
            r = client.post(f"{backend_url}/chat", json={"message": msg})
            r.raise_for_status()
            data = r.json()
            answer = data.get("answer", "(no answer)")
        except Exception as e:
            answer = f"백엔드 호출 실패: {e}"

        # 마지막 assistant placeholder를 실제 답변으로 교체
        if st.session_state.voc_messages and st.session_state.voc_messages[-1].get("role") == "assistant":
            st.session_state.voc_messages[-1]["content"] = answer
        else:
            st.session_state.voc_messages.append({"role": "assistant", "content": answer})

        st.session_state.voc_pending_message = None
        st.session_state.voc_status = "idle"
        st.session_state.voc_scroll_pending = True
        st.rerun()

    # ---------- chat area ----------
    chat_box = st.container(height=520, border=True)
    with chat_box:
        for m in st.session_state.voc_messages:
            with st.chat_message(m["role"]):
                st.markdown(m["content"])

        if st.session_state.voc_scroll_pending:
            scroll_to_bottom()
            st.session_state.voc_scroll_pending = False

    # ---------- input area ----------
    with st.form("voc_chat_form", clear_on_submit=True):
        col1, col2 = st.columns([8, 1])

        with col1:
            user_text = st.text_input(
                "질문 입력",
                placeholder="공정/운영 문의를 입력하세요",
                disabled=is_busy,
                label_visibility="collapsed",
                key="voc_input",
            )

        with col2:
            submitted = st.form_submit_button(
                "전송",
                disabled=is_busy,
                use_container_width=True,
            )

    # ---------- submit: enqueue ----------
    if submitted and st.session_state.voc_status == "idle":
        text = (user_text or "").strip()
        if not text:
            st.warning("질문을 입력한 뒤 전송하세요.")
        else:
            st.session_state.voc_messages.append({"role": "user", "content": text})
            st.session_state.voc_messages.append({"role": "assistant", "content": "응답 생성 중..."})
            st.session_state.voc_pending_message = text
            st.session_state.voc_status = "queued"
            st.session_state.voc_scroll_pending = True
            st.rerun()

    # ---------- busy: overlay + DOM lock ----------
    if is_busy:
        ui_lock("응답 생성 중입니다. 잠시만 기다려 주세요.")

    # ---------- phase: queued -> calling ----------
    if st.session_state.voc_status == "queued" and st.session_state.voc_pending_message:
        st.session_state.voc_status = "calling"
        st.rerun()
