from __future__ import annotations

import re
import uuid
from typing import Any, Dict, List

from backend.logs.timeline import build_timeline
from backend.logs.troubleshoot import recommend_troubleshooting
from backend.telemetry.store import append_jsonl
from backend.voc.rag.retriever import retrieve
from backend.llm.router import call_llm_chat


def _has_hangul(s: str) -> bool:
    return bool(re.search(r"[가-힣]", s or ""))


def _keyword_hits(text: str) -> bool:
    t = (text or "").lower()
    return any(k in t for k in ["로그", "timeline", "타임라인", "fail", "error", "exception", "traceback", "status="])


def _summarize_error_events(timeline: List[Dict[str, Any]], max_items: int = 10) -> str:
    errs = [e for e in (timeline or []) if e.get("error_like") or str(e.get("status", "")).upper() == "FAIL"]
    if not errs:
        return "에러/FAIL 후보 이벤트를 찾지 못했습니다."
    tail = errs[-max_items:]
    lines = []
    for e in tail:
        ts = e.get("ts", "")
        msg = e.get("message") or e.get("msg_name") or ""
        status = e.get("status") or ""
        work = e.get("work") or ""
        ceid = e.get("ceid") or ""
        err = e.get("error_msg") or ""
        parts = [p for p in [ts, msg, f"STATUS={status}" if status else "", f"WORK={work}" if work else "", f"CEID={ceid}" if ceid else "", err] if p]
        lines.append("- " + " | ".join(parts))
    return "\n".join(lines)


def run_agent(
    message: str,
    mode: str = "auto",
    log_text: str = "",
    filename: str = "",
    k: int = 5,
    include_debug: bool = False,
) -> Dict[str, Any]:
    interaction_id = str(uuid.uuid4())
    msg = (message or "").strip()
    if not msg:
        return {"interaction_id": interaction_id, "answer": "질문이 비어 있습니다. 질문을 입력해 주세요.", "sources": [], "steps": []}

    steps: List[Dict[str, Any]] = []
    sources: List[Dict[str, Any]] = []

    use_logs = (mode == "logs") or (mode == "auto" and (bool((log_text or "").strip()) or _keyword_hits(msg)))

    # --- LOGS branch ---
    if use_logs:
        if not (log_text or "").strip():
            answer = "로그 기반 분석을 위해 로그 텍스트(또는 파일 업로드)가 필요합니다. 로그를 업로드/붙여넣기 후 다시 요청해 주세요."
            return {"interaction_id": interaction_id, "answer": answer, "sources": [], "steps": steps}

        timeline_result = build_timeline(log_text, filename=filename)
        steps.append(
            {
                "tool": "logs.timeline",
                "result_meta": {
                    "total_lines": timeline_result.get("total_lines"),
                    "events": len(timeline_result.get("timeline") or []),
                },
            }
        )

        err_summary = _summarize_error_events(timeline_result.get("timeline") or [])
        steps.append({"tool": "logs.error_summary", "text": err_summary[:2000]})

        ts_result = recommend_troubleshooting(log_text=log_text, query="", k=k)
        steps.append({"tool": "logs.troubleshoot", "query": ts_result.get("query", ""), "matches": len(ts_result.get("matches") or [])})

        ctx_blocks: List[str] = []
        idx = 1

        # troubleshooting.md matches -> context
        for m in (ts_result.get("matches") or []):
            sp = m.get("section_path") or ""
            sn = m.get("snippet") or ""
            ctx_blocks.append(f"[{idx}] source=troubleshooting.md section={sp}\n{sn}")
            sources.append(
                {
                    "source": "troubleshooting.md",
                    "section_path": sp,
                    "score": m.get("lexical"),
                    "distance": m.get("distance"),
                }
            )
            idx += 1

        # additional RAG over entire docs
        q2 = " ".join([msg, ts_result.get("query", "")]).strip()
        hits = retrieve(q2, k=min(6, max(3, k)))
        steps.append({"tool": "voc.retrieve", "query": q2, "hits": len(hits)})

        for h in hits:
            meta = h.get("metadata") or {}
            src = meta.get("source", "unknown")
            sp = meta.get("section_path") or meta.get("section_title") or "unknown_section"
            doc = (h.get("document") or "").strip()
            if not doc:
                continue
            if len(doc) > 1800:
                doc = doc[:1800] + "\n...(중략)"
            ctx_blocks.append(f"[{idx}] source={src} section={sp}\n{doc}")
            sources.append({"source": src, "section_path": sp, "distance": h.get("distance")})
            idx += 1

        context = "\n\n".join(ctx_blocks).strip()

        system_msg = (
            "당신은 반도체 설비 로그 분석 및 트러블슈팅 지원 에이전트입니다.\n"
            "사용자는 초보자(아무것도 모름)라고 가정하고, 단계적으로 설명하세요.\n\n"
            "[언어 규칙]\n"
            "- 설명/문장은 반드시 한국어로만 작성하세요.\n"
            "- 기술 토큰/약어(S6F11, CEID, WORK, TOOL_CONDITION_REPLY 등)는 필요한 경우에만 그대로 언급 가능합니다.\n"
            "- 중국어/일본어(한자/가나)는 절대 사용하지 마세요.\n\n"
            "[근거 규칙]\n"
            "- 아래 [근거]에 있는 내용만 사용해 답변하세요.\n"
            "- 근거에 없는 내용은 추측하지 말고 '근거 부족'이라고 명시하고, 추가로 필요한 로그/정보를 질문하세요.\n"
        )

        user_msg = f"""[로그 에러 요약]
{err_summary}

[근거]
{context}

[요청]
{msg}

[출력 형식 - 반드시 준수]
1) 증상 요약(로그 기반)
2) 가능 원인(근거 기반, 가설일 경우 가설이라고 명시)
3) 권장 조치(트러블슈팅 문서 근거를 [1], [2]처럼 인용)
4) 추가 확인 항목(필요한 로그 키/상태/시점 등)
"""

        answer = call_llm_chat(system_msg, user_msg) or "(빈 응답)"
        if not _has_hangul(answer):
            answer = (
                call_llm_chat(system_msg, user_msg, retry_msg="위 답변은 한국어 설명이 부족합니다. 한국어로 다시 작성하세요.")
                or answer
            )

        append_jsonl(
            "agent_chat.jsonl",
            {
                "interaction_id": interaction_id,
                "kind": "agent_chat",
                "mode": mode,
                "message": msg,
                "filename": filename,
                "used_logs": True,
                "tool_steps": steps if include_debug else [],
                "sources": sources,
                "answer": answer,
            },
        )

        return {"interaction_id": interaction_id, "answer": answer, "sources": sources, "steps": steps if include_debug else []}

    # --- VOC branch (default) ---
    # 기존 /chat 로직을 그대로 재사용해서 “행동 일관성” 유지
    from backend.voc.api import ChatRequest, chat as voc_chat  # local import to avoid circulars

    resp = voc_chat(ChatRequest(message=msg))
    answer = getattr(resp, "answer", None) or (resp.get("answer") if isinstance(resp, dict) else "") or ""
    srcs = getattr(resp, "sources", None) or (resp.get("sources") if isinstance(resp, dict) else []) or []

    append_jsonl(
        "agent_chat.jsonl",
        {
            "interaction_id": interaction_id,
            "kind": "agent_chat",
            "mode": mode,
            "message": msg,
            "used_logs": False,
            "sources": srcs,
            "answer": answer,
        },
    )

    return {"interaction_id": interaction_id, "answer": answer, "sources": srcs, "steps": []}
