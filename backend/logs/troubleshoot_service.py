import re
from typing import Any, Dict, List, Tuple

from backend.logs.troubleshoot_retriever import retrieve_troubleshooting


# ---- 로그 파싱: MVP 수준(추후 강화 가능) ----
MSG_PAT = re.compile(r"\b([A-Z][A-Z0-9_]{2,})\b")
SxFy_PAT = re.compile(r"\bS\d+F\d+\b", re.IGNORECASE)
STATUS_PAT = re.compile(r"\bSTATUS=(PASS|FAIL)\b", re.IGNORECASE)
EXC_PAT = re.compile(r"\b(Exception|Traceback|ERROR)\b", re.IGNORECASE)
CEID_PAT = re.compile(r"\bCEID=\d+\b", re.IGNORECASE)
WORK_PAT = re.compile(r"\bWORK=[^\]\s]+\b", re.IGNORECASE)


def build_query_from_log_text(log_text: str) -> Tuple[str, Dict[str, Any]]:
    """
    대용량 로그에서 '트러블슈팅 검색에 유의미한 토큰'만 뽑아 query를 구성.
    - 메시지명(영문_대문자), SxFy, STATUS=FAIL, Exception, CEID=, WORK=
    """
    text = log_text or ""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    msg_tokens: List[str] = []
    sxfy_tokens: List[str] = []
    status_fail = False
    has_exc = False
    ceid_tokens: List[str] = []
    work_tokens: List[str] = []

    for ln in lines:
        for m in MSG_PAT.findall(ln):
            # 너무 흔한 토큰(예: INFO, HDR 등) 성격이면 추후 stoplist 가능
            msg_tokens.append(m.upper())

        for m in SxFy_PAT.findall(ln):
            sxfy_tokens.append(m.upper())

        st = STATUS_PAT.search(ln)
        if st and st.group(1).upper() == "FAIL":
            status_fail = True

        if EXC_PAT.search(ln):
            has_exc = True

        for m in CEID_PAT.findall(ln):
            ceid_tokens.append(m.upper())

        for m in WORK_PAT.findall(ln):
            work_tokens.append(m.upper())

    # 중복 제거(순서 유지)
    def uniq(seq: List[str]) -> List[str]:
        out = []
        seen = set()
        for x in seq:
            if x not in seen:
                out.append(x)
                seen.add(x)
        return out

    msg_tokens = uniq(msg_tokens)
    sxfy_tokens = uniq(sxfy_tokens)
    ceid_tokens = uniq(ceid_tokens)
    work_tokens = uniq(work_tokens)

    # 검색용 query 구성(짧지만 강한 토큰 중심)
    parts = []
    if status_fail:
        parts.append("STATUS=FAIL")
    if has_exc:
        parts.append("EXCEPTION")

    # 메시지명이 핵심(예: WORK_START_REQUEST)
    parts.extend(msg_tokens[:30])

    # 절차/이벤트 힌트
    parts.extend(sxfy_tokens[:10])
    parts.extend(ceid_tokens[:10])
    parts.extend(work_tokens[:10])

    query = " ".join(parts).strip()
    debug = {
        "status_fail": status_fail,
        "has_exception": has_exc,
        "msg_tokens": msg_tokens[:50],
        "sxfy": sxfy_tokens[:20],
        "ceid": ceid_tokens[:20],
        "work": work_tokens[:20],
        "line_count": len(lines),
    }
    return query, debug


def _lexical_score(query: str, doc: str, meta: Dict[str, Any]) -> int:
    """
    재랭킹용 간단 점수:
    - query의 주요 토큰이 섹션 제목/경로/본문에 얼마나 등장하는지
    """
    q = (query or "").upper()
    toks = re.findall(r"[A-Z0-9_]{3,}|\bSTATUS=FAIL\b|\bEXCEPTION\b", q)
    toks = list(dict.fromkeys(toks))

    text_u = (doc or "").upper()
    title_u = (meta.get("section_title") or "").upper()
    path_u = (meta.get("section_path") or "").upper()

    hit_title = sum(1 for t in toks if t in title_u)
    hit_path = sum(1 for t in toks if t in path_u)
    hit_body = sum(1 for t in toks if t in text_u)

    return hit_title * 6 + hit_path * 3 + hit_body * 1


def recommend_troubleshooting(log_text: str, top_n: int = 5, candidates: int = 30, source: str = "troubleshooting.md"):
    query, debug = build_query_from_log_text(log_text)

    # query가 비면 최소 폴백(전체 문장 일부라도 넣기)
    if not query:
        query = (log_text or "").strip().splitlines()[:10]
        query = " ".join(query) if isinstance(query, list) else str(query)

    # 1차 후보(벡터 검색, source 필터)
    # top_n보다 넉넉히 뽑아서 재랭킹
    cand = retrieve_troubleshooting(query=query, top_n=max(top_n, 10), candidates=candidates, source=source)

    # 2차 재랭킹(토큰 일치 + distance)
    ranked = []
    for it in cand:
        doc = it.get("document") or ""
        meta = it.get("metadata") or {}
        dist = float(it.get("distance", 1e9))
        lex = _lexical_score(query, doc, meta)

        # score: lexical을 크게, distance는 보조
        score = float(lex) - dist  # dist는 작을수록 좋으니 빼기

        excerpt = doc.strip()
        if len(excerpt) > 500:
            excerpt = excerpt[:500] + "\n...(중략)"

        ranked.append(
            {
                "title": meta.get("section_title") or meta.get("section_path") or "unknown",
                "section_path": meta.get("section_path") or "",
                "source": meta.get("source") or source,
                "score": score,
                "distance": dist,
                "excerpt": excerpt,
                "meta": meta,
            }
        )

    ranked.sort(key=lambda x: x["score"], reverse=True)

    out = ranked[:top_n]
    debug["query"] = query
    debug["cand_count"] = len(cand)
    return query, out, debug
