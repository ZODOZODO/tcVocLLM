import argparse
import json
import math
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import chromadb
from dotenv import load_dotenv

from backend.voc.rag.embeddings import embed_texts

load_dotenv()

CHROMA_DIR = os.getenv("CHROMA_DIR", "./data/chroma")
COLLECTION_NAME = os.getenv("CHROMA_COLLECTION", "tcvoc_docs")


def _parse_k_values(raw: str) -> List[int]:
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    ks = sorted({int(p) for p in parts if int(p) > 0})
    if not ks:
        raise ValueError("k_values must contain positive integers")
    return ks


def _load_queries(path: Path) -> List[Dict[str, Any]]:
    queries: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            raw = line.strip()
            if not raw:
                continue
            try:
                item = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON at line {line_no}: {exc}") from exc

            query = (item.get("query") or "").strip()
            if not query:
                raise ValueError(f"Missing query at line {line_no}")

            relevant_paths = item.get("relevant_section_paths") or []
            keywords = item.get("keywords") or []
            if not isinstance(relevant_paths, list) or not isinstance(keywords, list):
                raise ValueError(f"Invalid schema at line {line_no}: paths/keywords must be list")

            if not relevant_paths and not keywords:
                raise ValueError(f"Line {line_no} must include relevant_section_paths or keywords")

            queries.append(
                {
                    "id": item.get("id") or f"line_{line_no}",
                    "query": query,
                    "relevant_section_paths": relevant_paths,
                    "keywords": keywords,
                }
            )
    return queries


def _normalize(text: str) -> str:
    return (text or "").lower()


def _is_relevant(
    meta: Dict[str, Any],
    doc: str,
    relevant_paths: Iterable[str],
    keywords: Iterable[str],
) -> bool:
    section_path = (meta or {}).get("section_path") or ""
    section_title = (meta or {}).get("section_title") or ""

    if section_path and section_path in relevant_paths:
        return True

    combined = "\n".join([section_path, section_title, doc or ""])
    combined_norm = _normalize(combined)
    for kw in keywords:
        if _normalize(kw) in combined_norm:
            return True
    return False


def _dcg(relevances: List[int], k: int) -> float:
    score = 0.0
    for i, rel in enumerate(relevances[:k], start=1):
        if rel:
            score += rel / math.log2(i + 1)
    return score


def _ndcg(relevances: List[int], k: int, total_relevant: int) -> float:
    if total_relevant == 0:
        return 0.0
    dcg = _dcg(relevances, k)
    ideal_rels = [1] * min(total_relevant, k)
    idcg = _dcg(ideal_rels, k)
    return dcg / idcg if idcg > 0 else 0.0


def _mrr(relevances: List[int]) -> float:
    for i, rel in enumerate(relevances, start=1):
        if rel:
            return 1.0 / i
    return 0.0


def _recall_at_k(relevances: List[int], k: int, total_relevant: int) -> float:
    if total_relevant == 0:
        return 0.0
    hits = sum(relevances[:k])
    return hits / total_relevant


def _evaluate_query(
    query_item: Dict[str, Any],
    collection: chromadb.Collection,
    k_values: List[int],
) -> Dict[str, Any]:
    query = query_item["query"]
    relevant_paths = query_item["relevant_section_paths"]
    keywords = query_item["keywords"]

    q_emb = embed_texts([query])[0]
    max_k = max(k_values)

    res = collection.query(
        query_embeddings=[q_emb],
        n_results=max_k,
        include=["documents", "metadatas", "distances"],
    )

    docs: List[str] = (res.get("documents") or [[]])[0]
    metas: List[Dict[str, Any]] = (res.get("metadatas") or [[]])[0]
    dists: List[float] = (res.get("distances") or [[]])[0]

    relevances: List[int] = []
    hits: List[Dict[str, Any]] = []

    for idx, (doc, meta, dist) in enumerate(zip(docs, metas, dists), start=1):
        meta = meta or {}
        is_rel = _is_relevant(meta, doc or "", relevant_paths, keywords)
        relevances.append(1 if is_rel else 0)
        hits.append(
            {
                "rank": idx,
                "distance": dist,
                "section_path": meta.get("section_path"),
                "section_title": meta.get("section_title"),
                "source": meta.get("source"),
                "is_relevant": is_rel,
            }
        )

    total_relevant = len(relevant_paths) if relevant_paths else len({kw for kw in keywords})

    metrics = {"mrr": _mrr(relevances)}
    for k in k_values:
        metrics[f"recall@{k}"] = _recall_at_k(relevances, k, total_relevant)
        metrics[f"ndcg@{k}"] = _ndcg(relevances, k, total_relevant)

    return {
        "id": query_item["id"],
        "query": query,
        "relevant_section_paths": relevant_paths,
        "keywords": keywords,
        "metrics": metrics,
        "hits": hits,
    }


def _aggregate_results(results: List[Dict[str, Any]], k_values: List[int]) -> Dict[str, Any]:
    summary: Dict[str, float] = {"mrr": 0.0}
    for k in k_values:
        summary[f"recall@{k}"] = 0.0
        summary[f"ndcg@{k}"] = 0.0

    if not results:
        return summary

    for result in results:
        summary["mrr"] += result["metrics"]["mrr"]
        for k in k_values:
            summary[f"recall@{k}"] += result["metrics"][f"recall@{k}"]
            summary[f"ndcg@{k}"] += result["metrics"][f"ndcg@{k}"]

    count = len(results)
    for key in list(summary.keys()):
        summary[key] = summary[key] / count

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate RAG retrieval metrics.")
    parser.add_argument(
        "--queries",
        default="data/rag_eval/queries.jsonl",
        help="Path to queries.jsonl",
    )
    parser.add_argument(
        "--output",
        default="data/rag_eval/results.json",
        help="Path to write results.json",
    )
    parser.add_argument(
        "--k-values",
        default="1,3,5,10",
        help="Comma-separated list of k values for Recall/nDCG",
    )
    args = parser.parse_args()

    queries_path = Path(args.queries)
    output_path = Path(args.output)
    k_values = _parse_k_values(args.k_values)

    if not queries_path.exists():
        raise FileNotFoundError(f"queries.jsonl not found: {queries_path}")

    queries = _load_queries(queries_path)

    client = chromadb.PersistentClient(path=CHROMA_DIR)
    collection = client.get_or_create_collection(name=COLLECTION_NAME)

    results = [_evaluate_query(item, collection, k_values) for item in queries]
    summary = _aggregate_results(results, k_values)

    payload = {
        "summary": summary,
        "k_values": k_values,
        "num_queries": len(results),
        "queries": results,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print("[rag_eval] queries=", len(results))
    print("[rag_eval] output=", output_path)
    for key, value in summary.items():
        print(f"[rag_eval] {key}={value:.4f}")


if __name__ == "__main__":
    main()
