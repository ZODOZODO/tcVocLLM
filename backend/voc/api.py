import os
import re
from datetime import datetime
from typing import Any, Dict, List, Tuple

from dotenv import load_dotenv
from fastapi import APIRouter
from loguru import logger
from pydantic import BaseModel

from backend.llm.client import call_chat
from backend.voc.rag.retriever import retrieve

load_dotenv()

# 절차형 근거 판단 기준(근거에 '->' 라인이 충분히 많으면 절차형으로 간주)
PROCEDURE_MIN_LINES = int(os.getenv("PROCEDURE_MIN_LINES", "8"))
PROCEDURE_MAX_LINES = int(os.getenv("PROCEDURE_MAX_LINES", "80"))

# 컨텍스트 과다 방지(청크가 너무 길면 잘라서 넣기)
MAX_CHUNK_CHARS = int(os.getenv("MAX_CHUNK_CHARS", "1800"))

router = APIRouter()


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    answer: str
    sources: list[dict] = []


def _has_hangul(s: str) -> bool:
    return bool(re.search(r"[가-힣]", s or ""))


def _has_han_or_kana(s: str) -> bool:
    """
    중국어/일본어 문자(한자/가나)가 섞였는지 탐지.
    - 한자(공통 CJK): \u4E00-\u9FFF
    - 히라가나: \u3040-\u309F
    - 가타카나: \u30A0-\u30FF
    """
    if not s:
        return False
    return bool(re.search(r"[\u4E00-\u9FFF\u3040-\u309F\u30A0-\u30FF]", s))


def _sort_hits_in_doc_order(hits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    retriever가 같은 섹션에서 여러 청크를 줄 수 있으므로,
    문서/청크 순으로 정렬해 컨텍스트 연속성을 높임.
    """
    def key(h: Dict[str, Any]) -> Tuple[str, int, int]:
        meta = h.get("metadata") or {}
        src = meta.get("source", "")
        idx = meta.get("chunk_index", 10**9)
        sub = meta.get("sub_index", 0)
        try:
            idx = int(idx)
        except Exception:
            idx = 10**9
        try:
            sub = int(sub)
        except Exception:
            sub = 0
        return (src, idx, sub)

    return sorted(hits, key=key)


def _extract_procedure_steps(text: str) -> List[Dict[str, str]]:
    """
    문서에서 'A -> B : MSG ...' 형태 라인을 구조화하여 추출.
    - 원문을 그대로 출력하지 않기 위해, "구조화 데이터"로만 제공
    """
    steps: List[Dict[str, str]] = []
    if not text:
        return steps

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue

        # 리스트 마커 제거(원문 의미는 유지)
        if line.startswith("- "):
            line = line[2:].strip()
        if line.startswith("*"):
            line = line.lstrip("*").strip()

        m = re.match(r"^(?P<src>.+?)\s*->\s*(?P<dst>.+?)\s*:\s*(?P<msg>.+?)\s*$", line)
        if not m:
            continue

        src = m.group("src").strip()
        dst = m.group("dst").strip()
        msg = m.group("msg").strip()

        steps.append({"src": src, "dst": dst, "msg": msg})

    # 중복 제거(순서 유지)
    seen = set()
    uniq: List[Dict[str, str]] = []
    for s in steps:
        key = (s["src"], s["dst"], s["msg"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(s)

    return uniq


@router.get("/health")
def health():
    return {"ok": True, "ts": datetime.utcnow().isoformat()}


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    question = (req.message or "").strip()
    if not question:
        return ChatResponse(answer="질문이 비어 있습니다. 질문을 입력해 주세요.", sources=[])

    hits = retrieve(question, k=6)
    if not hits:
        return ChatResponse(
            answer=(
                "관련 문서 근거를 찾지 못했습니다.\n"
                "설비명/공정명/상황(예: PORT, SxFy, 메시지명, 에러코드)을 추가로 주시면 더 정확히 찾을 수 있습니다."
            ),
            sources=[],
        )

    # UI/검증용 sources 구성
    sources = []
    for h in hits:
        meta = h.get("metadata") or {}
        sources.append(
            {
                "source": meta.get("source", "unknown"),
                "section_path": meta.get("section_path"),
                "chunk_index": meta.get("chunk_index", -1),
                "sub_index": meta.get("sub_index", 0),
                "distance": h.get("distance"),
            }
        )

    ordered_hits = _sort_hits_in_doc_order(hits)

    # 근거(context) 구성 (청크가 너무 길면 잘라서 프롬프트 과다 방지)
    context_blocks = []
    for idx, h in enumerate(ordered_hits, start=1):
        meta = h.get("metadata") or {}
        src = meta.get("source", "unknown")
        sp = meta.get("section_path") or meta.get("section_title") or "unknown_section"
        doc = (h.get("document") or "").strip()
        if not doc:
            continue
        if len(doc) > MAX_CHUNK_CHARS:
            doc = doc[:MAX_CHUNK_CHARS] + "\n...(중략: 청크가 길어 일부만 포함됨)"
        context_blocks.append(f"[{idx}] source={src} section={sp}\n{doc}")

    context = "\n\n".join(context_blocks).strip()

    # 근거에서 절차형 라인 추출(구조화)
    combined_docs = "\n".join([(h.get("document") or "") for h in ordered_hits])
    proc_steps = _extract_procedure_steps(combined_docs)

    # 절차형 근거 판단: 문서 형태 기반(질문 키워드 하드코딩 없음)
    require_procedure = len(proc_steps) >= PROCEDURE_MIN_LINES

    # 언어 규칙 명확화: 설명 문장은 한국어, 기술 토큰/원문 단어는 허용
    system_msg = (
        "당신은 반도체 공정/운영 VOC 지원 챗봇입니다.\n"
        "사용자는 초보자(아무것도 모름)라고 가정하고, 상세하고 단계적으로 설명하세요.\n"
        "\n"
        "[언어 규칙]\n"
        "- 설명/문장은 반드시 한국어로만 작성하세요.\n"
        "- 근거에 등장하는 기술 토큰/약어(APC, MES, S6F11 등), 메시지명은 필요한 경우에만 그대로 언급 가능합니다.\n"
        "- 중국어/일본어(한자/가나)는 절대 사용하지 마세요.\n"
        "\n"
        "[근거 규칙]\n"
        "- 아래 [근거]에 있는 내용만 사용해 답변하세요.\n"
        "- 근거에 없는 내용은 추측하지 말고 '근거 부족'이라고 명시하고, 추가로 필요한 정보를 질문하세요.\n"
        "- 근거에 없는 예시(임의 사례, 임의 공정 파라미터 등)를 만들지 마세요.\n"
        "\n"
        "[중요]\n"
        "- 만약 절차형 근거가 주어지면, 답변은 '순서'를 지키되 원문 형태(예: A -> B : MSG)를 그대로 복사해 출력하지 마세요.\n"
        "- 즉, 원문 절차를 그대로 붙여넣는 섹션(원문 절차 흐름)을 만들지 마세요.\n"
    )

    # 절차형이면 "출력 금지" 참고자료를 제공(순서 유지 목적)
    procedure_hint = ""
    if require_procedure:
        steps = proc_steps[:PROCEDURE_MAX_LINES]
        # 모델이 그대로 복사하지 않도록: 구조화 + 출력금지 강하게 명시
        # (표현은 '->' 형태를 피하고, src/dst/msg 필드로만 제공)
        lines = []
        for i, s in enumerate(steps, start=1):
            lines.append(f"{i}. src={s['src']} | dst={s['dst']} | msg={s['msg']}")
        procedure_hint = (
            "\n[절차 참고자료(출력 금지)]\n"
            "- 아래 목록은 근거에서 추출한 절차의 '구조화 데이터'입니다.\n"
            "- 답변에 이 목록을 그대로 복사/인용/재출력하지 마세요.\n"
            "- 대신, 아래 순서를 유지하면서 초보자가 이해할 수 있게 단계별로 풀어서 설명하세요.\n"
            "- 각 단계에서 '누가→누구에게 무엇을 보내는지/받는지'를 자연어로 설명하세요.\n"
            "\n"
            + "\n".join(lines)
            + "\n"
        )

    user_msg = f"""[근거]
{context}
{procedure_hint}

[질문]
{question}

[출력 형식 - 반드시 준수]
1) 결론(질문에 대한 핵심 답변)
2) 상세 설명(초보자 기준으로 단계/흐름을 풀어서 설명)
3) 근거 인용(관련 근거를 [1], [2]처럼 인용)
"""

    try:
        answer = call_chat(system_msg, user_msg) or "(빈 응답)"

        # 1차: 한글이 거의 없으면 한국어로 재작성
        if not _has_hangul(answer):
            answer2 = call_chat(
                system_msg,
                user_msg,
                retry_msg=(
                    "위 답변은 한국어 설명이 부족합니다. "
                    "설명 문장을 반드시 한국어로만, 형식에 맞춰 다시 작성하세요. "
                    "중국어/일본어(한자/가나)는 절대 쓰지 마세요."
                ),
            )
            if answer2:
                answer = answer2

        # 2차: 중국어/일본어 문자가 섞이면 한국어로만 재작성
        if _has_han_or_kana(answer):
            answer2 = call_chat(
                system_msg,
                user_msg,
                retry_msg=(
                    "답변에 중국어/일본어(한자/가나)가 섞여 있습니다. "
                    "전체 답변을 한국어 설명 문장으로만 다시 작성하세요. "
                    "근거에 없는 예시는 만들지 마세요."
                ),
            )
            if answer2:
                answer = answer2

        return ChatResponse(answer=answer, sources=sources)

    except Exception as e:
        logger.exception("LLM 호출 실패")
        return ChatResponse(answer=f"[오류] LLM 호출 실패: {e}", sources=sources)
