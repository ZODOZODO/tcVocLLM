import os
import re
from datetime import datetime
from typing import Any, Dict, List, Tuple, Optional

import httpx
from dotenv import load_dotenv
from fastapi import APIRouter
from loguru import logger
from pydantic import BaseModel

from backend.voc.rag.retriever import retrieve

load_dotenv()

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct-q4_K_M")

# 절차형 근거 판단 기준(근거에 '->' 라인이 충분히 많으면 절차 누락 방지 모드)
PROCEDURE_MIN_LINES = int(os.getenv("PROCEDURE_MIN_LINES", "8"))
PROCEDURE_MAX_LINES = int(os.getenv("PROCEDURE_MAX_LINES", "80"))

# 컨텍스트 과다 방지(청크가 너무 길면 잘라서 넣기)
MAX_CHUNK_CHARS = int(os.getenv("MAX_CHUNK_CHARS", "1800"))

# Ollama 옵션
OLLAMA_TEMPERATURE = float(os.getenv("OLLAMA_TEMPERATURE", "0.2"))
OLLAMA_NUM_PREDICT = int(os.getenv("OLLAMA_NUM_PREDICT", "1000"))
OLLAMA_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", "240"))

router = APIRouter()

# httpx Client 재사용(요청당 오버헤드 감소)
_http = httpx.Client(timeout=OLLAMA_TIMEOUT)


@router.on_event("shutdown")
def _shutdown():
    try:
        _http.close()
    except Exception:
        pass


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
    문서/청크 순으로 정렬해 컨텍스트와 절차 추출의 연속성을 높임.
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


def _extract_arrow_lines(text: str) -> List[str]:
    """
    문서에서 'A -> B : MSG ...' 형태 라인을 추출(원문 보존).
    """
    out: List[str] = []
    if not text:
        return out

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
        if m:
            src = m.group("src").strip()
            dst = m.group("dst").strip()
            msg = m.group("msg").strip()
            out.append(f"{src} -> {dst} : {msg}")

    return out


def _validate_contains_lines(answer: str, required_lines: List[str]) -> List[str]:
    """
    답변에 required_lines가 모두 포함되었는지 검사(부분 문자열 포함으로 체크).
    - '한 글자도 바꾸지 말고' 정책을 유지하기 위해 엄격 비교 유지.
    """
    missing = []
    a = answer or ""
    for line in required_lines:
        if line not in a:
            missing.append(line)
    return missing


def _call_ollama(system_msg: str, user_msg: str, retry_msg: Optional[str] = None) -> str:
    """
    Ollama /api/chat 호출.
    """
    messages = [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_msg},
    ]
    if retry_msg:
        messages.append({"role": "user", "content": retry_msg})

    r = _http.post(
        f"{OLLAMA_BASE_URL}/api/chat",
        json={
            "model": OLLAMA_MODEL,
            "stream": False,
            "messages": messages,
            "options": {
                "temperature": OLLAMA_TEMPERATURE,
                "num_predict": OLLAMA_NUM_PREDICT,
            },
        },
    )
    r.raise_for_status()
    data: dict[str, Any] = r.json()
    return ((data.get("message") or {}).get("content") or "").strip()


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

    # 근거에서 절차 라인(arrow lines) 추출
    combined_docs = "\n".join([(h.get("document") or "") for h in ordered_hits])
    arrow_lines = _extract_arrow_lines(combined_docs)

    # "절차형 근거" 판단: 근거 형태 기반(질문 키워드 하드코딩 없음)
    require_procedure = len(arrow_lines) >= PROCEDURE_MIN_LINES

    # 언어 규칙 명확화: 설명 문장은 한국어, 기술 토큰/원문 라인은 허용
    system_msg = (
        "당신은 반도체 공정/운영 VOC 지원 챗봇입니다.\n"
        "사용자는 초보자(아무것도 모름)라고 가정하고, 상세하고 단계적으로 설명하세요.\n"
        "\n"
        "[언어 규칙]\n"
        "- 설명/문장은 반드시 한국어로만 작성하세요.\n"
        "- 단, 근거에 등장하는 기술 토큰/약어(APC, MES, S6F11 등), 메시지명, 원문 절차 라인은 원문 그대로 사용/인용하는 것은 허용됩니다.\n"
        "- 중국어/일본어(한자/가나)는 절대 사용하지 마세요.\n"
        "\n"
        "[근거 규칙]\n"
        "- 아래 [근거]에 있는 내용만 사용해 답변하세요.\n"
        "- 근거에 없는 내용은 추측하지 말고 '근거 부족'이라고 명시하고, 추가로 필요한 정보를 질문하세요.\n"
        "- 근거에 없는 예시(임의 사례, 임의 공정 파라미터 등)를 만들지 마세요.\n"
    )

    procedure_block = ""
    required_lines: List[str] = []
    if require_procedure:
        required_lines = arrow_lines[:PROCEDURE_MAX_LINES]
        procedure_block = (
            "\n[절차 라인(근거에서 추출됨)]\n"
            "아래 라인들은 절차 흐름의 핵심입니다.\n"
            "답변의 '원문 절차 흐름' 섹션에 아래 라인들을 반드시 포함하세요.\n"
            "- 반드시 ```text``` 코드블록 안에 그대로 붙여넣으세요.\n"
            "- 한 글자도 바꾸지 말고 동일 순서로 포함하세요.\n"
            "그리고 각 라인이 무엇을 의미하는지 단계별로 초보자에게 설명하세요.\n\n"
            "```text\n" + "\n".join(required_lines) + "\n```\n"
        )

    user_msg = f"""[근거]
{context}
{procedure_block}

[질문]
{question}

[출력 형식 - 반드시 준수]
1) 결론(질문에 대한 핵심 답변)
2) 상세 설명(초보자 기준으로 단계/흐름을 풀어서 설명)
3) 근거 인용(관련 근거를 [1], [2]처럼 인용)
4) 절차형 근거가 제공된 경우에만:
   - "원문 절차 흐름" 섹션에 위 ```text``` 라인들을 그대로 포함
   - 각 단계 해설을 덧붙이기
"""

    try:
        answer = _call_ollama(system_msg, user_msg) or "(빈 응답)"

        # 1차: 한글이 거의 없으면 한국어로 재작성
        if not _has_hangul(answer):
            answer2 = _call_ollama(
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
            answer2 = _call_ollama(
                system_msg,
                user_msg,
                retry_msg=(
                    "답변에 중국어/일본어(한자/가나)가 섞여 있습니다. "
                    "전체 답변을 한국어 설명 문장으로만 다시 작성하세요. "
                    "근거의 기술 토큰/원문 라인만 예외적으로 그대로 인용 가능합니다. "
                    "근거에 없는 예시는 만들지 마세요."
                ),
            )
            if answer2:
                answer = answer2

        # 3차: 절차형 근거인 경우, 라인 누락 검증 후 1회 재시도
        if require_procedure and required_lines:
            missing = _validate_contains_lines(answer, required_lines)
            if missing:
                sample = missing[:10]
                retry_msg = (
                    "답변에 '원문 절차 흐름'이 누락되었거나 원문 라인이 변경되었습니다.\n"
                    "아래 라인들을 반드시 ```text``` 코드블록 안에, 한 글자도 바꾸지 말고 동일 순서로 포함해 다시 작성하세요.\n"
                    "설명 문장은 한국어로만 작성하고, 근거 밖 예시는 만들지 마세요.\n"
                    f"누락 예시(일부):\n- " + "\n- ".join(sample)
                )
                answer2 = _call_ollama(system_msg, user_msg, retry_msg=retry_msg)
                if answer2:
                    answer = answer2

            if _has_han_or_kana(answer):
                answer3 = _call_ollama(
                    system_msg,
                    user_msg,
                    retry_msg=(
                        "답변에 외국어(한자/가나)가 남아 있습니다. "
                        "설명 문장은 한국어로만 최종 정리해서 다시 작성하세요. "
                        "근거 밖 예시는 만들지 마세요."
                    ),
                )
                if answer3:
                    answer = answer3

        return ChatResponse(answer=answer, sources=sources)

    except Exception as e:
        logger.exception("Ollama 호출 실패")
        return ChatResponse(answer=f"[오류] Ollama 호출 실패: {e}", sources=sources)
