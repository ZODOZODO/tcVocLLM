import hashlib

import httpx
import streamlit as st

from ui.ui_helper import (
    decode_bytes_best_effort,
    get_http_client,
    ui_lock,
    ui_unlock,
    scroll_to_bottom,
)


def _file_signature(name: str, raw: bytes) -> str:
    h = hashlib.sha1()
    h.update(raw)
    return f"{name}::{len(raw)}::{h.hexdigest()}"


def render_agent_tab(BACKEND_URL: str) -> None:
    st.subheader("Agent (LLM + RAG + Logs Tool)")

    ss = st.session_state

    # ---------- state init ----------
    ss.setdefault("agent_messages", [])  # [{"role","content","interaction_id"?}]
    ss.setdefault("agent_status", "idle")  # idle|queued|calling
    ss.setdefault("agent_pending_message", None)
    ss.setdefault("agent_scroll_pending", False)

    ss.setdefault("agent_mode", "auto")  # auto|voc|logs
    ss.setdefault("agent_k", 5)
    ss.setdefault("agent_debug", False)

    ss.setdefault("agent_log_text", "")
    ss.setdefault("agent_log_filename", "")
    ss.setdefault("agent_log_sig", "")

    client: httpx.Client = get_http_client(timeout=240)

    # ---------- 1) calling phase: UI 렌더링 전에 먼저 처리하고 즉시 rerun ----------
    if ss.agent_status == "calling" and ss.agent_pending_message:
        msg = ss.agent_pending_message

        with st.spinner("에이전트 실행 중..."):
            try:
                r = client.post(
                    f"{BACKEND_URL}/agent/chat",
                    json={
                        "message": msg,
                        "mode": ss.agent_mode,
                        "log_text": ss.agent_log_text,
                        "filename": ss.agent_log_filename,
                        "k": int(ss.agent_k),
                        "include_debug": bool(ss.agent_debug),
                    },
                )
                r.raise_for_status()
                data = r.json()
                answer = (data.get("answer") or "").strip() or "(빈 응답)"
                interaction_id = data.get("interaction_id") or ""
                steps = data.get("steps") or []
            except Exception as e:
                answer = f"[오류] 백엔드 호출 실패: {e}"
                interaction_id = ""
                steps = []

        ss.agent_messages.append({"role": "assistant", "content": answer, "interaction_id": interaction_id})

        if ss.agent_debug and steps:
            ss.agent_messages.append(
                {
                    "role": "assistant",
                    "content": "DEBUG steps\n```json\n" + str(steps) + "\n```",
                }
            )

        ss.agent_pending_message = None
        ss.agent_status = "idle"
        ss.agent_scroll_pending = True

        ui_unlock()
        st.rerun()
        return  # ✅ 중요: 아래 UI 렌더링이 중복되지 않게 종료

    # ---------- 2) normal UI render ----------
    is_busy = ss.agent_status in ("queued", "calling")
    if not is_busy:
        ui_unlock()

    # ---------- file upload (optional) ----------
    up = st.file_uploader(
        "로그 파일(선택): 업로드하면 로그 기반 분석이 가능합니다.",
        type=["log", "txt"],
        accept_multiple_files=False,
        key="agent_uploader",
    )
    if up is not None:
        try:
            raw = up.getvalue()
            sig = _file_signature(up.name, raw)
            if sig != ss.agent_log_sig:
                ss.agent_log_sig = sig
                ss.agent_log_text = decode_bytes_best_effort(raw)
                ss.agent_log_filename = up.name
        except Exception as e:
            st.error(f"파일 읽기 실패: {e}")

    if ss.agent_log_text:
        st.caption(f"업로드됨: {ss.agent_log_filename}")
        st.text_area(
            "로그 미리보기(일부)",
            value=ss.agent_log_text[:4000],
            height=200,
            label_visibility="collapsed",
            key="agent_log_preview",
        )

    # ---------- controls ----------
    c1, c2, c3 = st.columns([2, 1, 1])
    with c1:
        ss.agent_mode = st.selectbox(
            "모드",
            ["auto", "voc", "logs"],
            index=["auto", "voc", "logs"].index(ss.agent_mode),
            disabled=is_busy,
            key="agent_mode_sel",
        )
    with c2:
        ss.agent_k = st.number_input(
            "k",
            min_value=1,
            max_value=20,
            value=int(ss.agent_k),
            step=1,
            disabled=is_busy,
            key="agent_k_in",
        )
    with c3:
        ss.agent_debug = st.checkbox(
            "디버그(steps)",
            value=bool(ss.agent_debug),
            disabled=is_busy,
            key="agent_debug_ck",
        )

    st.divider()

    # ---------- chat area ----------
    chat_box = st.container(height=520, border=True)
    with chat_box:
        for m in ss.agent_messages:
            with st.chat_message(m["role"]):
                st.markdown(m["content"])

        if is_busy:
            with st.chat_message("assistant"):
                st.markdown("에이전트 실행 중...")

        if ss.agent_scroll_pending:
            scroll_to_bottom()
            ss.agent_scroll_pending = False

    # ---------- input ----------
    with st.form("agent_input_form", clear_on_submit=True):
        col1, col2 = st.columns([6, 1])
        with col1:
            user_text = st.text_input(
                "질문",
                disabled=is_busy,
                label_visibility="collapsed",
                placeholder="질문을 입력하세요 (로그 업로드 시 로그 기반 분석 가능)",
            )
        with col2:
            submitted = st.form_submit_button(
                "전송",
                disabled=is_busy,
                use_container_width=True,
            )

    # ---------- submit -> queue ----------
    if submitted and ss.agent_status == "idle":
        text = (user_text or "").strip()
        if not text:
            st.warning("질문을 입력한 뒤 전송하세요.")
        else:
            ss.agent_messages.append({"role": "user", "content": text})
            ss.agent_pending_message = text
            ss.agent_status = "queued"
            ss.agent_scroll_pending = True
            st.rerun()

    # ---------- queued -> calling (먼저 busy UI를 한 번 렌더링) ----------
    if ss.agent_status == "queued" and ss.agent_pending_message:
        ui_lock()
        ss.agent_status = "calling"
        st.rerun()

    # ---------- busy lock (queued/calling 상태에서 입력 잠금) ----------
    if is_busy:
        ui_lock()
