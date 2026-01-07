import httpx
import streamlit as st

from ui.ui_helper import (
    get_http_client,
    ui_lock,
    ui_unlock,
    scroll_to_bottom,
)

def render_voc_tab(BACKEND_URL: str) -> None:
    # ---------- state init ----------
    if "voc_messages" not in st.session_state:
        st.session_state.voc_messages = []  # [{"role":"user|assistant","content": "..."}]
    if "voc_status" not in st.session_state:
        st.session_state.voc_status = "idle"  # idle | queued | calling
    if "voc_pending_message" not in st.session_state:
        st.session_state.voc_pending_message = None
    if "voc_scroll_pending" not in st.session_state:
        st.session_state.voc_scroll_pending = False

    is_busy = st.session_state.voc_status in ("queued", "calling")

    # idle이면 혹시 남아있을 수 있는 잠금 흔적을 해제(안전장치)
    if not is_busy:
        ui_unlock()

    # ✅ httpx Client 재사용
    client: httpx.Client = get_http_client(timeout=240)

    # ---------- phase: calling (실제 백엔드 호출 run) ----------
    # calling 단계에서는 UI를 그리기 전에 호출을 수행하고 결과 반영 후 rerun
    if st.session_state.voc_status == "calling" and st.session_state.voc_pending_message:
        msg = st.session_state.voc_pending_message

        try:
            r = client.post(f"{BACKEND_URL}/chat", json={"message": msg})
            r.raise_for_status()
            data = r.json()
            answer = data.get("answer", "(no answer)")
        except Exception as e:
            answer = f"백엔드 호출 실패: {e}"

        # ✅ 대기용 placeholder를 messages에 넣지 않으므로, 여기서 답변을 1회 append만 하면 됨
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

        # ✅ busy일 때는 "화면에만" 임시 표시(메시지 리스트에는 저장하지 않음)
        if is_busy:
            with st.chat_message("assistant"):
                st.markdown("응답 생성 중...")

        # 렌더링이 끝난 뒤 스크롤 실행
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
            st.session_state.voc_pending_message = text
            st.session_state.voc_status = "queued"
            st.session_state.voc_scroll_pending = True
            st.rerun()

    # ---------- busy: overlay + DOM lock ----------
    if is_busy:
        ui_lock()

    # ---------- phase: queued -> calling ----------
    # queued run의 목적은 "응답 생성 중..." + 잠금 상태를 먼저 렌더링하기 위함
    if st.session_state.voc_status == "queued" and st.session_state.voc_pending_message:
        st.session_state.voc_status = "calling"
        st.rerun()
