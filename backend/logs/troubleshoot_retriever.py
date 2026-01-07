import os
import re
from typing import Any, Dict, List, Optional

import chromadb
from dotenv import load_dotenv

# 기존 임베딩(Ollama) 재사용: 최소 변경
from backend.voc.rag.embeddings import embed_texts

load_dotenv()

CHROMA_DIR = os.getenv("CHROMA_DIR", "./data/chroma")
COLLECTION_NAME = os.getenv("CHROMA_COLLECTION", "tcvoc_docs")

_client = chromadb.PersistentClient(path=CHROMA_DIR)
_col = _client.get_or_create_collection(name=COLLECTION_NAME)


def _safe_where(source: str) -> Dict[str, Any]:
    # metadata에 source를 넣고 ingest 하고 있으므로 where로 필터
    # (Chroma 버전 차이로 where가 쿼리에서 실패할 수 있어 try/fallback)
    return {"source": source}


def retrieve_troubleshooting(
    query: str,
    top_n: int = 5,
    candidates: int = 30,
    source: str = "troubleshooting.md",
) -> List[Dict[str, Any]]:
    q = (query or "").strip()
    if not q:
        return []

    q_emb = embed_texts([q])[0]

    # 1) where 필터 시도
    res = None
    try:
        res = _col.query(
            query_embeddings=[q_emb],
            n_results=max(candidates, top_n),
            include=["documents", "metadatas", "distances"],
            where=_safe_where(source),
        )
    except Exception:
        # 2) fallback: 필터 없이 뽑고 후처리로 source만 남김
        res = _col.query(
            query_embeddings=[q_emb],
            n_results=max(candidates, top_n) * 3,
            include=["documents", "metadatas", "distances"],
        )

    docs = (res.get("documents") or [[]])[0]
    metas = (res.get("metadatas") or [[]])[0]
    dists = (res.get("distances") or [[]])[0]

    items: List[Dict[str, Any]] = []
    for doc, meta, dist in zip(docs, metas, dists):
        meta = meta or {}
        if meta.get("source") != source:
            continue
        items.append({"document": doc or "", "metadata": meta, "distance": float(dist)})

    # 섹션 단위 중복 제거(같은 section_path면 가장 가까운 것 1개)
    best: Dict[str, Dict[str, Any]] = {}
    for it in items:
        sp = (it["metadata"].get("section_path") or "").strip()
        key = sp or f'{it["metadata"].get("source","unknown")}::{it["metadata"].get("chunk_index",-1)}'
        if key not in best or it["distance"] < best[key]["distance"]:
            best[key] = it

    # distance 낮은 순
    out = sorted(best.values(), key=lambda x: x.get("distance", 1e9))
    return out[:top_n]
