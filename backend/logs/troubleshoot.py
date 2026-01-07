import os
import re
from typing import Any, Dict, List, Tuple

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
        if not (is_error_like(ev) or (ev.status or "").upper() == "FAIL"):
            continue

        err = ev.kv.get("ERRORMSG") or ev.kv.get("ERRMSG") or ""
        fail_events.append(
            {
                "msg": (ev.msg_name or ""),
                "status": (ev.status or ""),
                "work": (ev.work or ""),
                "ceid": (ev.ceid or ""),
                "err": err,
            }
        )

    # 마지막 쪽(최근) FAIL 위주로 조합
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

    # 중복 제거(순서 유지)
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


def recommend_troubleshooting(log_text: str = "", query: str = "", k: int = 5) -> Dict[str, Any]:
    q = (query or "").strip()
    if not q:
        q = _extract_query_from_log(log_text)

    if not q:
        return {"query": "", "matches": [], "note": "검색어를 만들 정보가 부족합니다. FAIL 라인 또는 ERRORMSG가 포함된 로그를 넣어 주세요."}

    client = chromadb.PersistentClient(path=CHROMA_DIR)
    col = client.get_or_create_collection(name=COLLECTION_NAME)

    q_emb = embed_texts([q])[0]

    # troubleshooting.md만 검색
    res = col.query(
        query_embeddings=[q_emb],
        n_results=max(k * 10, 30),
        include=["documents", "metadatas", "distances"],
        where={"source": TROUBLE_SOURCE},
    )

    docs = (res.get("documents") or [[]])[0]
    metas = (res.get("metadatas") or [[]])[0]
    dists = (res.get("distances") or [[]])[0]

    toks = _tokens(q)

    items: List[Dict[str, Any]] = []
    for doc, meta, dist in zip(docs, metas, dists):
        meta = meta or {}
        doc_s = (doc or "").strip()
        doc_u = doc_s.upper()
        title_u = (meta.get("section_title") or "").upper()
        path_u = (meta.get("section_path") or "").upper()

        exact, ht, hp, hb = _lexical_counts(doc_u, title_u, path_u, toks)
        lexical = ht * 5 + hp * 3 + hb * 1

        items.append(
            {
                "source": meta.get("source", ""),
                "section_path": meta.get("section_path", ""),
                "distance": float(dist),
                "exact": exact,
                "lexical": lexical,
                "snippet": doc_s[:800],
            }
        )

    # exact > lexical > distance
    items.sort(key=lambda it: (-it["exact"], -it["lexical"], it["distance"]))
    return {"query": q, "matches": items[:k]}
