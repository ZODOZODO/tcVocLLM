# backend/logs/troubleshoot.py
from typing import Any, Dict, List

from backend.voc.rag.retriever import retrieve


def recommend_troubleshooting(query: str, k: int = 5) -> Dict[str, Any]:
    """
    troubleshooting.md에서 우선 추천하고, 부족하면 전체 문서로 폴백.
    """
    q = (query or "").strip()
    if not q:
        return {"items": [], "note": "query empty"}

    hits = retrieve(q, k=max(k * 3, 12))

    # 1) troubleshooting.md 우선 필터
    ts = [h for h in hits if (h.get("metadata") or {}).get("source") == "troubleshooting.md"]

    picked = ts[:k]
    note = "from troubleshooting.md"

    # 2) troubleshooting에서 못 찾으면 폴백
    if not picked:
        picked = hits[:k]
        note = "fallback to all docs"

    items: List[Dict[str, Any]] = []
    for h in picked:
        meta = h.get("metadata") or {}
        doc = (h.get("document") or "").strip()
        # 너무 길면 UI용으로 축약
        excerpt = doc if len(doc) <= 500 else doc[:500] + " ..."

        items.append(
            {
                "source": meta.get("source"),
                "section_path": meta.get("section_path"),
                "distance": h.get("distance"),
                "excerpt": excerpt,
            }
        )

    return {"items": items, "note": note, "query": q}
