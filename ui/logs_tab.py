import hashlib
from typing import Any, Dict, List, Optional

import pandas as pd
import streamlit as st

from ui.ui_helper import get_http_client, decode_bytes_best_effort, scroll_to_anchor

ANCHOR_ID_TIMELINE = "logs-timeline-anchor"
ANCHOR_ID_TS = "logs-troubleshoot-anchor"


def _file_signature(name: str, raw: bytes) -> str:
    h = hashlib.sha1()
    h.update(raw)
    return f"{name}::{len(raw)}::{h.hexdigest()}"


def _normalize_troubleshoot_items(obj: Any) -> List[Dict[str, Any]]:
    """
    백엔드 응답 형태가 바뀌어도 최대한 표시가 되도록 흡수.
    기대 가능한 케이스:
    - {"recommendations": [...]} / {"items": [...]} / {"results": [...]}
    - {"answer": "...", "sources": [...]} (VOC처럼)
    - 그냥 list [...]
    """
    if obj is None:
        return []

    # list 직접 반환
    if isinstance(obj, list):
        return [x if isinstance(x, dict) else {"text": str(x)} for x in obj]

    if not isinstance(obj, dict):
        return [{"text": str(obj)}]

    for k in ("recommendations", "items", "results", "hits", "candidates"):
        v = obj.get(k)
        if isinstance(v, list):
            return [x if isinstance(x, dict) else {"text": str(x)} for x in v]

    # VOC 스타일
    if "answer" in obj and isinstance(obj.get("answer"), str):
        out = [{"title": "추천 결과", "content": obj.get("answer")}]
        srcs = obj.get("sources")
        if isinstance(srcs, list) and srcs:
            out[0]["sources"] = srcs
        return out

    # fallback
    return [obj]


def render_logs_tab(backend_url: str) -> None:
    st.subheader("설비 로그 분석 (MVP)")

    ss = st.session_state

    # ---------- state ----------
    ss.setdefault("logs_text", "")
    ss.setdefault("logs_filename", "")
    ss.setdefault("logs_file_sig", "")

    ss.setdefault("logs_timeline_result", None)
    ss.setdefault("logs_troubleshoot_result", None)

    ss.setdefault("logs_scroll_pending", False)

    # filters
    ss.setdefault("logs_selected_carid", "(전체)")
    ss.setdefault("logs_selected_lotid", "(전체)")
    ss.setdefault("logs_only_error", False)

    # troubleshoot ui
    ss.setdefault("logs_ts_only_error", True)  # 트러블슈팅은 기본 에러 기반으로
    ss.setdefault("logs_ts_limit", 5)          # 보여줄 추천 개수(표시용)
    ss.setdefault("logs_ts_last_sig", "")      # 같은 파일에서 추천 재실행 여부 판단

    def request_scroll():
        ss.logs_scroll_pending = True

    uploaded = st.file_uploader(
        "로그 파일 업로드",
        type=["log", "txt"],
        accept_multiple_files=False,
        help="예: TESTEQP01.log",
        key="logs_uploader",
    )

    # ✅ 파일이 실제로 바뀐 경우에만 결과 초기화 (위젯 생성 전에만 state를 세팅)
    if uploaded is not None:
        try:
            raw = uploaded.getvalue()
            sig = _file_signature(uploaded.name, raw)

            if sig != ss.logs_file_sig:
                ss.logs_file_sig = sig
                ss.logs_text = decode_bytes_best_effort(raw)
                ss.logs_filename = uploaded.name

                # 결과/필터 초기화
                ss.logs_timeline_result = None
                ss.logs_troubleshoot_result = None
                ss.logs_selected_carid = "(전체)"
                ss.logs_selected_lotid = "(전체)"
                ss.logs_only_error = False

                ss.logs_ts_last_sig = ""  # 새 파일이면 추천도 새로
        except Exception as e:
            st.error(f"파일 읽기 실패: {e}")

    if ss.logs_text:
        st.caption(f"업로드됨: {ss.logs_filename}")
        st.text_area(
            "로그 미리보기(일부)",
            value=ss.logs_text[:4000],
            height=220,
            label_visibility="collapsed",
            key="logs_preview",
        )

    # ---------- actions ----------
    a1, a2, _ = st.columns([1, 1, 5])

    with a1:
        run_timeline = st.button(
            "타임라인 생성",
            disabled=not bool(ss.logs_text.strip()),
            use_container_width=True,
            key="logs_run_timeline_btn",
        )

    with a2:
        run_ts = st.button(
            "트러블슈팅 추천",
            disabled=not bool(ss.logs_text.strip()),
            use_container_width=True,
            key="logs_run_ts_btn",
        )

    # ----- call timeline -----
    if run_timeline:
        try:
            with st.spinner("타임라인 생성 중..."):
                client = get_http_client(timeout=240)
                r = client.post(
                    f"{backend_url}/logs/timeline",
                    json={
                        "log_text": ss.logs_text,
                        "filename": ss.logs_filename,
                    },
                )
                r.raise_for_status()
                ss.logs_timeline_result = r.json()
                request_scroll()
        except Exception as e:
            ss.logs_timeline_result = None
            st.error(f"/logs/timeline 호출 실패: {e}")
            st.info("Swagger: http://127.0.0.1:8000/docs 에 POST /logs/timeline 이 있는지 확인하세요.")

    # ----- call troubleshoot -----
    if run_ts:
        try:
            with st.spinner("트러블슈팅 추천 생성 중..."):
                client = get_http_client(timeout=240)
                r = client.post(
                    f"{backend_url}/logs/troubleshoot",
                    json={
                        "log_text": ss.logs_text,
                        "filename": ss.logs_filename,
                    },
                )
                r.raise_for_status()
                ss.logs_troubleshoot_result = r.json()
                ss.logs_ts_last_sig = ss.logs_file_sig  # 마지막 실행 파일 시그니처 기록
                request_scroll()
        except Exception as e:
            ss.logs_troubleshoot_result = None
            st.error(f"/logs/troubleshoot 호출 실패: {e}")
            st.info("Swagger: http://127.0.0.1:8000/docs 에 POST /logs/troubleshoot 이 있는지 확인하세요.")

    # ---------- timeline result ----------
    tl = ss.logs_timeline_result
    if not tl:
        st.info("로그 업로드 후 ‘타임라인 생성’을 누르면 결과가 표시됩니다.")
    else:
        total_lines = tl.get("total_lines")
        timeline: List[Dict[str, Any]] = tl.get("timeline") or []

        st.markdown(f'<div id="{ANCHOR_ID_TIMELINE}"></div>', unsafe_allow_html=True)
        st.success(f"타임라인 완료: 전체 라인 {total_lines}, 타임라인 이벤트 {len(timeline)}")

        st.checkbox(
            "에러/FAIL/Exception 후보만 보기",
            value=ss.logs_only_error,
            key="logs_only_error",
            on_change=request_scroll,
        )

        carids = sorted({(x.get("carid") or "") for x in timeline if (x.get("carid") or "")})
        lotids = sorted({(x.get("lotid") or "") for x in timeline if (x.get("lotid") or "")})

        car_opts = ["(전체)"] + carids
        lot_opts = ["(전체)"] + lotids

        # ✅ 옵션에 없으면, 위젯 생성 전에만 보정
        if ss.logs_selected_carid not in car_opts:
            ss.logs_selected_carid = "(전체)"
        if ss.logs_selected_lotid not in lot_opts:
            ss.logs_selected_lotid = "(전체)"

        f1, f2 = st.columns([2, 2])
        with f1:
            st.selectbox(
                "CARID 필터",
                car_opts,
                key="logs_selected_carid",
                on_change=request_scroll,
            )
        with f2:
            st.selectbox(
                "LOTID 필터",
                lot_opts,
                key="logs_selected_lotid",
                on_change=request_scroll,
            )

        sel_carid = ss.logs_selected_carid
        sel_lotid = ss.logs_selected_lotid
        only_error = ss.logs_only_error

        def _pass(x: dict) -> bool:
            if only_error and not x.get("error_like"):
                return False
            if sel_carid != "(전체)" and (x.get("carid") != sel_carid):
                return False
            if sel_lotid != "(전체)" and (x.get("lotid") != sel_lotid):
                return False
            return True

        filtered = [x for x in timeline if _pass(x)]

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
            "error_msg",
            "raw",
        ]

        def _norm_row(x: dict) -> dict:
            return {c: x.get(c, "") for c in cols}

        df = pd.DataFrame([_norm_row(x) for x in filtered], columns=cols)
        if "ts" in df.columns:
            try:
                df = df.sort_values(by=["ts"], ascending=True)
            except Exception:
                pass

        view_cols = [c for c in cols if c != "raw"]
        st.caption("타임라인(시간순 / 조건: WORK+CEID 동시 존재 이벤트만 포함)")
        st.dataframe(df[view_cols], use_container_width=True, height=520)

        with st.expander("원문(raw) 포함 JSON 보기"):
            st.json(tl)

    # ---------- troubleshoot result ----------
    tsr = ss.logs_troubleshoot_result
    if tsr:
        st.markdown(f'<div id="{ANCHOR_ID_TS}"></div>', unsafe_allow_html=True)
        st.success("트러블슈팅 추천 완료")

        # 표시 옵션 (UI만, session_state 재대입 금지)
        o1, o2, _ = st.columns([2, 2, 4])
        with o1:
            st.checkbox(
                "추천 결과에서 에러 후보 중심으로 보기(표시 옵션)",
                value=ss.logs_ts_only_error,
                key="logs_ts_only_error",
                on_change=request_scroll,
            )
        with o2:
            st.number_input(
                "추천 표시 개수",
                min_value=1,
                max_value=30,
                value=int(ss.logs_ts_limit),
                step=1,
                key="logs_ts_limit",
                on_change=request_scroll,
            )

        items = _normalize_troubleshoot_items(tsr)

        # 표시용 정규화: title/content/score/source 중심으로
        normed: List[Dict[str, Any]] = []
        for it in items:
            if not isinstance(it, dict):
                normed.append({"title": "", "content": str(it)})
                continue
            normed.append(
                {
                    "title": it.get("title") or it.get("section_path") or it.get("section_title") or it.get("name") or "",
                    "score": it.get("score", it.get("rerank_score", it.get("distance", ""))),
                    "source": it.get("source") or (it.get("metadata") or {}).get("source", ""),
                    "content": it.get("content") or it.get("text") or it.get("document") or it.get("answer") or "",
                }
            )

        # 표로 먼저 보여주고, 상세는 expander로
        df_ts = pd.DataFrame(normed, columns=["title", "score", "source", "content"])

        # content는 길면 표에서는 보기 힘드니 축약 컬럼 추가
        df_ts["content_preview"] = df_ts["content"].apply(
            lambda s: (str(s)[:200] + " ...") if s and len(str(s)) > 200 else str(s)
        )

        st.caption("트러블슈팅 추천(문서 기반)")
        st.dataframe(
            df_ts[["title", "score", "source", "content_preview"]],
            use_container_width=True,
            height=300,
        )

        with st.expander("트러블슈팅 추천 원문(JSON) 보기"):
            st.json(tsr)

        # 개별 상세
        with st.expander("추천 상세 보기"):
            for i, row in enumerate(normed[: int(ss.logs_ts_limit)], start=1):
                title = row.get("title") or f"추천 {i}"
                st.markdown(f"**{i}. {title}**")
                meta_line = []
                if row.get("score") != "":
                    meta_line.append(f"score={row.get('score')}")
                if row.get("source"):
                    meta_line.append(f"source={row.get('source')}")
                if meta_line:
                    st.caption(" / ".join(meta_line))
                if row.get("content"):
                    st.markdown(str(row.get("content")))
                st.divider()

    # ---------- scroll ----------
    if ss.logs_scroll_pending:
        # 우선 타임라인 앵커를 시도하고, 없으면 트러블슈팅 앵커로
        if ss.logs_timeline_result:
            scroll_to_anchor(ANCHOR_ID_TIMELINE)
        elif ss.logs_troubleshoot_result:
            scroll_to_anchor(ANCHOR_ID_TS)
        ss.logs_scroll_pending = False
