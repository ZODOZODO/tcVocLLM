import httpx
import streamlit as st

from ui.ui_helper import (
    get_http_client,
    ui_lock,
    ui_unlock,
    scroll_to_bottom,
)


def render_voc_tab(BACKEND_URL: str) -> None:
    st.subheader("VOC Chatbot (Docs RAG)")

    ss = st.session_state
    ss.setdefault("voc_messages", [])          # [{"role":"user|assistant","content": "..."}]
    ss.setdefault("voc_status", "idle")        # idle | queued | calling
    ss.setdefault("voc_pending_message", None)
    ss.setdefault("voc_scroll_pending", False)
    ss.setdefault("voc_use_agent", False)      # Agent toggle

    client: httpx.Client = get_http_client(timeout=240)

    # ---------- 1) calling phase: UI 렌더링 전에 먼저 처리하고 즉시 rerun ----------
    if ss.voc_status == "calling" and ss.voc_pending_message:
        question = ss.voc_pending_message

        with st.spinner("응답 생성 중..."):
            try:
                if ss.voc_use_agent:
                    r = client.post(
                        f"{BACKEND_URL}/agent/chat",
                        json={
                            "message": question,
                            "mode": "voc",
                            "k": 6,
                            "include_debug": False,
                        },
                    )
                else:
                    r = client.post(f"{BACKEND_URL}/chat", json={"message": question})

                r.raise_for_status()
                data = r.json()
                answer = (data.get("answer") or "").strip() or "(빈 응답)"
            except Exception as e:
                answer = f"[오류] 백엔드 호출 실패: {e}"

        ss.voc_messages.append({"role": "assistant", "content": answer})
        ss.voc_pending_message = None
        ss.voc_status = "idle"
        ss.voc_scroll_pending = True

        ui_unlock()
        st.rerun()
        return  # ✅ 중요: 아래 UI 렌더링이 중복되지 않게 종료

    # ---------- 2) normal UI render ----------
    is_busy = ss.voc_status in ("queued", "calling")
    if not is_busy:
        ui_unlock()

    c1, c2 = st.columns([2, 3])
    with c1:
        ss.voc_use_agent = st.checkbox(
            "Agent로 실행(도구 오케스트레이션)",
            value=bool(ss.voc_use_agent),
            disabled=is_busy,
            key="voc_use_agent_ck",
        )
    with c2:
        st.caption("기본은 /chat, Agent 모드는 /agent/chat(mode=voc) 호출")

    # ---------- chat history ----------
    chat_box = st.container(height=520, border=True)
    with chat_box:
        for m in ss.voc_messages:
            with st.chat_message(m["role"]):
                st.markdown(m["content"])

        if is_busy:
            with st.chat_message("assistant"):
                st.markdown("응답 생성 중...")

        if ss.voc_scroll_pending:
            scroll_to_bottom()
            ss.voc_scroll_pending = False

    # ---------- input ----------
    with st.form("voc_input_form", clear_on_submit=True):
        col1, col2 = st.columns([6, 1])
        with col1:
            user_text = st.text_input(
                "질문",
                disabled=is_busy,
                label_visibility="collapsed",
                placeholder="질문을 입력하세요 (docs/md 근거 기반)",
            )
        with col2:
            submitted = st.form_submit_button(
                "전송",
                disabled=is_busy,
                use_container_width=True,
            )

    # ---------- submit -> queue ----------
    if submitted and ss.voc_status == "idle":
        text = (user_text or "").strip()
        if not text:
            st.warning("질문을 입력한 뒤 전송하세요.")
        else:
            ss.voc_messages.append({"role": "user", "content": text})
            ss.voc_pending_message = text
            ss.voc_status = "queued"
            ss.voc_scroll_pending = True
            st.rerun()

    # ---------- queued -> calling (먼저 '응답 생성 중...'을 렌더링하기 위한 1회 사이클) ----------
    if ss.voc_status == "queued" and ss.voc_pending_message:
        ui_lock()
        ss.voc_status = "calling"
        st.rerun()
