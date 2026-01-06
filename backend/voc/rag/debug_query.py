import os
import sys
from typing import Any, Dict, List

import chromadb
from dotenv import load_dotenv

from backend.voc.rag.embeddings import embed_texts  # ✅ 경로 수정

load_dotenv()

CHROMA_DIR = os.getenv("CHROMA_DIR", "./data/chroma")
COLLECTION_NAME = os.getenv("CHROMA_COLLECTION", "tcvoc_docs")


def main():
    if len(sys.argv) < 2:
        print('Usage: python -m backend.voc.rag.debug_query "질문"')
        sys.exit(1)

    query = sys.argv[1].strip()
    if not query:
        print("Empty query")
        sys.exit(1)

    client = chromadb.PersistentClient(path=CHROMA_DIR)
    col = client.get_or_create_collection(name=COLLECTION_NAME)

    count = col.count()
    print(f"[debug] collection={COLLECTION_NAME} count={count}")
    print(f"[debug] query={query}")

    q_emb = embed_texts([query])[0]

    res = col.query(
        query_embeddings=[q_emb],
        n_results=20,
        include=["documents", "metadatas", "distances"],
    )

    docs: List[str] = (res.get("documents") or [[]])[0]
    metas: List[Dict[str, Any]] = (res.get("metadatas") or [[]])[0]
    dists: List[float] = (res.get("distances") or [[]])[0]

    for i, (doc, meta, dist) in enumerate(zip(docs, metas, dists), start=1):
        meta = meta or {}
        src = meta.get("source", "unknown")
        sp = meta.get("section_path") or meta.get("section_title") or ""
        print(f"\n#{i} dist={dist:.4f} source={src} section_path={sp}")
        print((doc or "").strip())


if __name__ == "__main__":
    main()
