import os
import re
from typing import Any, Dict, List, Tuple, Optional

import chromadb
from dotenv import load_dotenv

from backend.voc.rag.embeddings import embed_texts
from backend.logs.parser import parse_line
from backend.logs.timeline import is_error_like

load_dotenv()

CHROMA_DIR = os.getenv("CHROMA_DIR", "./data/chroma")
COLLECTION_NAME = os.getenv("CHROMA_COLLECTION", "tcvoc_docs")

# troubleshooting.md의 rel 경로가 ingest에서 source로 들어간 값과 같아야 함
TROUBLE_SOURCE = os.getenv("TROUBLE_SOURCE", "troubleshooting.md")

# Reranker (학습 없이 ML 추론만)
RERANK_ENABLE = os.getenv("RERANK_ENABLE", "1").strip() not in ("0", "false", "False", "FALSE")
RERANK_MODEL = os.getenv("RERANK_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")
RERANK_BATCH_SIZE = int(os.getenv("RERANK_BATCH_SIZE", "16"))


def _tokens(text: str) -> List[str]:
    q = (text or "").strip()
    if not q:
        return []
    toks = re.findall(r"[A-Za-z0-9_]+|[가-힣]+", q)
    toks = [t for t in toks if len(t) >= 2]
    return list(dict.fromkeys([t.upper() for t in toks]))


def _is_alnum_token(t: str) -> bool:
    return bool(re.fullmatch(r"[A-Z0-9_]+", t or ""))


def _extract_query_from_log(log_text: str) -> str:
    """
    로그에서 장애 시그니처를 뽑아 추천 검색어로 만든다.
    - FAIL/ERROR/Exception 중심
    - msg_name, STATUS, WORK/CEID, ERRORMSG 등을 조합
    """
    parts: List[str] = []
    fail_events: List[Dict[str, str]] = []

    for raw in (log_text or "").splitlines():
        ev = parse_line(raw)
        if not ev:
            continue

        # FAIL/ERROR 후보
        status = (getattr(ev, "status", "") or ev.kv.get("STATUS") or "").upper()
        if not (is_error_like(ev) or status == "FAIL"):
            continue

        err = ev.kv.get("ERRORMSG") or ev.kv.get("ERRMSG") or ""
        fail_events.append(
            {
                "msg": (getattr(ev, "msg_name", "") or ""),
                "status": (getattr(ev, "status", "") or ev.kv.get("STATUS") or ""),
                "work": (getattr(ev, "work", "") or ""),
                "ceid": (getattr(ev, "ceid", "") or ""),
                "err": err,
            }
        )

    # 마지막(최근) FAIL 위주로 조합
    for fe in fail_events[-8:]:
        if fe["msg"]:
            parts.append(fe["msg"])
        if fe["status"]:
            parts.append(f"STATUS={fe['status']}")
        if fe["work"]:
            parts.append(f"WORK={fe['work']}")
        if fe["ceid"]:
            parts.append(f"CEID={fe['ceid']}")
        if fe["err"]:
            parts.append(fe["err"])

    dedup = list(dict.fromkeys([p for p in parts if p.strip()]))
    return " ".join(dedup).strip()


def _lexical_counts(doc_u: str, title_u: str, path_u: str, toks: List[str]) -> Tuple[int, int, int, int]:
    exact = 0
    hit_title = 0
    hit_path = 0
    hit_body = 0

    for t in toks:
        if _is_alnum_token(t):
            pat = re.compile(rf"(?<![A-Z0-9_]){re.escape(t)}(?![A-Z0-9_])")
            in_title = bool(pat.search(title_u))
            in_path = bool(pat.search(path_u))
            in_body = bool(pat.search(doc_u))
        else:
            in_title = t in title_u
            in_path = t in path_u
            in_body = t in doc_u

        if in_title or in_path or in_body:
            if _is_alnum_token(t):
                exact += 1
            if in_title:
                hit_title += 1
            if in_path:
                hit_path += 1
            if in_body:
                hit_body += 1

    return exact, hit_title, hit_path, hit_body


def _source_matches(meta_source: str) -> bool:
    """
    ingest에서 source가 다음 중 무엇으로 들어가도 TROUBLE_SOURCE에 매칭되도록 완화:
    - troubleshooting.md
    - docs/troubleshooting.md
    - ./docs/troubleshooting.md
    - path\\to\\troubleshooting.md
    """
    ms = (meta_source or "").replace("\\", "/").lstrip("./")
    ts = (TROUBLE_SOURCE or "").replace("\\", "/").lstrip("./")
    return ms == ts or ms.endswith("/" + ts) or ms.endswith(ts)


# ---- Reranker: 사전학습 모델 추론(학습 없음) ----
_RERANKER = None
_RERANKER_ERR: Optional[str] = None


def _get_reranker():
    global _RERANKER, _RERANKER_ERR
    if _RERANKER is not None or _RERANKER_ERR is not None:
        return _RERANKER

    if not RERANK_ENABLE:
        _RERANKER_ERR = "disabled"
        return None

    try:
        # 지연 import: 의존성이 없으면 fallback
        from sentence_transformers import CrossEncoder  # type: ignore

        _RERANKER = CrossEncoder(RERANK_MODEL)
        return _RERANKER
    except Exception as e:
        _RERANKER = None
        _RERANKER_ERR = f"{type(e).__name__}: {e}"
        return None


def _rerank_scores(query: str, passages: List[str]) -> Tuple[List[float], Optional[str]]:
    """
    (query, passage) 쌍에 대해 CrossEncoder 점수 산출.
    실패 시 빈 점수 + 에러 문자열 반환.
    """
    model = _get_reranker()
    if model is None:
        return [], _RERANKER_ERR

    try:
        pairs = [(query, p) for p in passages]
        scores: List[float] = []
        for i in range(0, len(pairs), RERANK_BATCH_SIZE):
            batch = pairs[i : i + RERANK_BATCH_SIZE]
            # CrossEncoder.predict는 float 리스트 반환
            out = model.predict(batch)
            # numpy/torch 타입이 섞일 수 있어 float로 캐스팅
            scores.extend([float(x) for x in out])
        return scores, None
    except Exception as e:
        return [], f"{type(e).__name__}: {e}"


def recommend_troubleshooting(log_text: str = "", query: str = "", k: int = 5) -> Dict[str, Any]:
    """
    2-Stage Retrieval:
    1) embedding vector search로 후보를 넓게 수집 (recall)
    2) CrossEncoder reranker로 재정렬 (precision, ML inference)
    """
    q = (query or "").strip()
    if not q:
        q = _extract_query_from_log(log_text)

    if not q:
        return {
            "query": "",
            "matches": [],
            "items": [],
            "note": "검색어를 만들 정보가 부족합니다. FAIL 라인 또는 ERRORMSG가 포함된 로그를 넣어 주세요.",
        }

    client = chromadb.PersistentClient(path=CHROMA_DIR)
    col = client.get_or_create_collection(name=COLLECTION_NAME)

    q_emb = embed_texts([q])[0]

    # troubleshooting 문서가 source 매칭 실패로 0건이 되는 문제를 피하기 위해
    # 넓게 쿼리 후 메타 source로 필터링
    res = col.query(
        query_embeddings=[q_emb],
        n_results=max(k * 20, 50),
        include=["documents", "metadatas", "distances"],
    )

    docs = (res.get("documents") or [[]])[0]
    metas = (res.get("metadatas") or [[]])[0]
    dists = (res.get("distances") or [[]])[0]

    # source 필터
    triplets: List[Tuple[str, Dict[str, Any], float]] = []
    for doc, meta, dist in zip(docs, metas, dists):
        meta = meta or {}
        if _source_matches(meta.get("source", "")):
            triplets.append(((doc or "").strip(), meta, float(dist)))

    note = ""
    if not triplets:
        note = (
            "troubleshooting 문서(source)로 필터링된 결과가 0건입니다. "
            "ingest 메타의 source 값과 TROUBLE_SOURCE 환경변수를 확인하세요."
        )

    toks = _tokens(q)

    # 1차: 기존 lexical/distance 특징 추출
    items: List[Dict[str, Any]] = []
    for doc_s, meta, dist in triplets:
        doc_u = doc_s.upper()
        title_u = (meta.get("section_title") or "").upper()
        path_u = (meta.get("section_path") or "").upper()

        exact, ht, hp, hb = _lexical_counts(doc_u, title_u, path_u, toks)
        lexical = ht * 5 + hp * 3 + hb * 1

        items.append(
            {
                "source": meta.get("source", ""),
                "section_path": meta.get("section_path", ""),
                "section_title": meta.get("section_title", ""),
                "distance": float(dist),
                "exact": int(exact),
                "lexical": int(lexical),
                "snippet": doc_s[:800],
            }
        )

    # 2차: ML reranker 적용 (가능하면)
    passages = [it["snippet"] for it in items]
    rerank_scores, rerank_err = _rerank_scores(q, passages) if passages else ([], None)

    if rerank_scores and len(rerank_scores) == len(items):
        for it, sc in zip(items, rerank_scores):
            it["rerank_score"] = float(sc)

        # reranker 우선 정렬: score desc
        items.sort(key=lambda it: (-it.get("rerank_score", 0.0), it.get("distance", 1e9)))
        used_reranker = True
    else:
        # fallback: exact > lexical > distance
        items.sort(key=lambda it: (-it["exact"], -it["lexical"], it["distance"]))
        used_reranker = False

    topk = items[:k]

    out: Dict[str, Any] = {
        "query": q,
        "matches": topk,  # UI 호환
        "items": topk,
        "note": note,
        "used_reranker": used_reranker,
    }
    if rerank_err and used_reranker is False:
        out["reranker_error"] = rerank_err
    out["total_candidates"] = len(items)
    return out
