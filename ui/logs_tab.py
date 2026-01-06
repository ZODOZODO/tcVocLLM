import hashlib
from typing import Any, Dict, List

import streamlit as st
import pandas as pd

from ui.ui_helper import get_http_client, decode_bytes_best_effort, scroll_to_anchor

ANCHOR_ID = "logs-timeline-anchor"


def _file_signature(name: str, raw: bytes) -> str:
    h = hashlib.sha1()
    h.update(raw)
    return f"{name}::{len(raw)}::{h.hexdigest()}"


def render_logs_tab(backend_url: str) -> None:
    st.subheader("설비 로그 분석 (MVP)")

    # ---------- state ----------
    if "logs_text" not in st.session_state:
        st.session_state.logs_text = ""
    if "logs_filename" not in st.session_state:
        st.session_state.logs_filename = ""
    if "logs_timeline_result" not in st.session_state:
        st.session_state.logs_timeline_result = None
    if "logs_file_sig" not in st.session_state:
        st.session_state.logs_file_sig = ""
    if "logs_scroll_pending" not in st.session_state:
        st.session_state.logs_scroll_pending = False

    def request_scroll():
        st.session_state.logs_scroll_pending = True

    uploaded = st.file_uploader(
        "로그 파일 업로드",
        type=["log", "txt"],
        accept_multiple_files=False,
        help="예: TESTEQP01.log",
        key="logs_uploader",
    )

    # ✅ 파일이 실제로 바뀐 경우에만 결과 초기화
    if uploaded is not None:
        try:
            raw = uploaded.getvalue()
            sig = _file_signature(uploaded.name, raw)

            if sig != st.session_state.logs_file_sig:
                st.session_state.logs_file_sig = sig
                st.session_state.logs_text = decode_bytes_best_effort(raw)
                st.session_state.logs_filename = uploaded.name
                st.session_state.logs_timeline_result = None
        except Exception as e:
            st.error(f"파일 읽기 실패: {e}")

    if st.session_state.logs_text:
        st.caption(f"업로드됨: {st.session_state.logs_filename}")
        st.text_area(
            "로그 미리보기(일부)",
            value=st.session_state.logs_text[:4000],
            height=220,
            label_visibility="collapsed",
            key="logs_preview",
        )

    col1, _ = st.columns([1, 4])
    with col1:
        run = st.button(
            "타임라인 생성",
            disabled=not bool(st.session_state.logs_text.strip()),
            use_container_width=True,
            key="logs_run_btn",
        )

    if run:
        try:
            with st.spinner("타임라인 생성 중..."):
                client = get_http_client(timeout=240)
                r = client.post(
                    f"{backend_url}/logs/timeline",
                    json={
                        "log_text": st.session_state.logs_text,
                        "filename": st.session_state.logs_filename,
                    },
                )
                r.raise_for_status()
                st.session_state.logs_timeline_result = r.json()
                # ✅ 결과 생성 직후 결과 영역으로 이동
                request_scroll()
        except Exception as e:
            st.session_state.logs_timeline_result = None
            st.error(f"/logs/timeline 호출 실패: {e}")
            st.info("백엔드 Swagger: http://127.0.0.1:8000/docs 에 POST /logs/timeline 이 있는지 확인하세요.")

    result = st.session_state.logs_timeline_result
    if not result:
        st.info("로그 업로드 후 ‘타임라인 생성’을 누르면 결과가 표시됩니다.")
        return

    total_lines = result.get("total_lines")
    timeline: List[Dict[str, Any]] = result.get("timeline") or []

    # ✅ 결과 영역 앵커(스크롤 튐 완화 목적)
    st.markdown(f'<div id="{ANCHOR_ID}"></div>', unsafe_allow_html=True)

    st.success(f"완료: 전체 라인 {total_lines}, 타임라인 이벤트 {len(timeline)}")

    # ----- filters -----
    only_error = st.checkbox(
        "에러/FAIL/Exception 후보만 보기",
        value=False,
        key="logs_only_error",
        on_change=request_scroll,
    )

    carids = sorted({(x.get("carid") or "") for x in timeline if (x.get("carid") or "")})
    lotids = sorted({(x.get("lotid") or "") for x in timeline if (x.get("lotid") or "")})

    fcol1, fcol2 = st.columns([2, 2])
    with fcol1:
        sel_carid = st.selectbox(
            "CARID 필터",
            ["(전체)"] + carids,
            key="logs_sel_carid",
            on_change=request_scroll,
        )
    with fcol2:
        sel_lotid = st.selectbox(
            "LOTID 필터",
            ["(전체)"] + lotids,
            key="logs_sel_lotid",
            on_change=request_scroll,
        )

    def _pass(x: dict) -> bool:
        if only_error and not x.get("error_like"):
            return False
        if sel_carid != "(전체)" and (x.get("carid") != sel_carid):
            return False
        if sel_lotid != "(전체)" and (x.get("lotid") != sel_lotid):
            return False
        return True

    filtered = [x for x in timeline if _pass(x)]

    # ----- table formatting -----
    # 컬럼이 항상 일정하게 보이도록 “표준 컬럼 세트” 구성
    # (백엔드가 어떤 키를 주든, 없는 값은 공백 처리)
    cols = [
        "ts",
        "eqpid",
        "work",
        "ceid",
        "direction",
        "message",
        "status",
        "error_like",
        "carid",
        "lotid",
        "raw",
    ]

    def _norm_row(x: dict) -> dict:
        row = {c: x.get(c, "") for c in cols}
        return row

    df = pd.DataFrame([_norm_row(x) for x in filtered], columns=cols)

    # 정렬(있으면 ts 기준)
    if "ts" in df.columns:
        try:
            df = df.sort_values(by=["ts"], ascending=True)
        except Exception:
            pass

    # raw는 기본 표에서 숨기고, expander에서만 보기 (가독성 개선)
    view_cols = [c for c in cols if c != "raw"]

    st.caption("타임라인(시간순 / 조건: WORK+CEID 동시 존재 이벤트만 포함)")
    st.dataframe(df[view_cols], use_container_width=True, height=520)

    with st.expander("원문(raw) 포함 JSON 보기"):
        st.json(result)

    # ✅ rerun 후 결과 영역으로 다시 이동(필터 변경/생성 직후)
    if st.session_state.logs_scroll_pending:
        scroll_to_anchor(ANCHOR_ID)
        st.session_state.logs_scroll_pending = False
