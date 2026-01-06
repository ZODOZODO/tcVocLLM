import os
import hashlib
from pathlib import Path
from typing import List, Dict, Tuple, Optional

import chromadb
from dotenv import load_dotenv

from backend.voc.rag.embeddings import embed_texts

load_dotenv()

DOCS_DIR = Path(os.getenv("DOCS_DIR", "./data/docs"))
CHROMA_DIR = os.getenv("CHROMA_DIR", "./data/chroma")
COLLECTION_NAME = os.getenv("CHROMA_COLLECTION", "tcvoc_docs")

# MD 전용
SUPPORTED_MD_EXT = {".md", ".markdown"}


def _read_text_file(p: Path) -> str:
    for enc in ("utf-8", "utf-8-sig", "cp949"):
        try:
            return p.read_text(encoding=enc)
        except Exception:
            pass
    return p.read_text(errors="ignore")


def _chunk_text(text: str, max_chars: int = 900, overlap: int = 120) -> List[str]:
    text = (text or "").replace("\r\n", "\n").strip()
    if not text:
        return []

    chunks: List[str] = []
    start = 0
    n = len(text)

    while start < n:
        end = min(start + max_chars, n)
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end == n:
            break
        start = max(0, end - overlap)

    return chunks


def _stable_id(*parts: str) -> str:
    raw = "::".join(parts).encode("utf-8", errors="ignore")
    return hashlib.sha1(raw).hexdigest()


def _parse_markdown_sections(md: str) -> List[Dict]:
    md = (md or "").replace("\r\n", "\n")
    lines = md.splitlines()

    sections: List[Dict] = []
    in_code_fence = False

    h1: Optional[str] = None
    h2: Optional[str] = None
    h3: Optional[str] = None

    current_level: Optional[int] = None
    current_title: Optional[str] = None
    current_body: List[str] = []

    def flush():
        nonlocal current_level, current_title, current_body, h1, h2, h3
        if current_level is None or current_title is None:
            return

        body = "\n".join(current_body).strip()

        # 빈 헤더 섹션 제외
        if not body:
            return

        path_parts = []
        if h1:
            path_parts.append(h1)
        if h2:
            path_parts.append(h2)
        if h3:
            path_parts.append(h3)

        section_path = " > ".join(path_parts) if path_parts else current_title

        sections.append(
            {
                "heading_level": current_level,
                "section_title": current_title,
                "section_path": section_path,
                "content": body,
            }
        )

    for raw in lines:
        line = raw.rstrip("\n")

        if line.strip().startswith("```"):
            in_code_fence = not in_code_fence
            if current_level is not None:
                current_body.append(line)
            continue

        if not in_code_fence:
            m = None
            if line.startswith("# "):
                m = (1, line[2:].strip())
            elif line.startswith("## "):
                m = (2, line[3:].strip())
            elif line.startswith("### "):
                m = (3, line[4:].strip())

            if m:
                flush()
                level, title = m

                if level == 1:
                    h1, h2, h3 = title, None, None
                elif level == 2:
                    if h1 is None:
                        h1 = "(Untitled)"
                    h2, h3 = title, None
                elif level == 3:
                    if h1 is None:
                        h1 = "(Untitled)"
                    if h2 is None:
                        h2 = "(Untitled)"
                    h3 = title

                current_level = level
                current_title = title
                current_body = []
                continue

        if current_level is not None:
            current_body.append(line)

    flush()
    return sections


def ingest() -> Tuple[int, int]:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    client = chromadb.PersistentClient(path=CHROMA_DIR)
    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )

    files = [
        p for p in DOCS_DIR.rglob("*")
        if p.is_file() and p.suffix.lower() in SUPPORTED_MD_EXT
    ]

    file_count = 0
    total_chunks = 0

    ids: List[str] = []
    docs: List[str] = []
    metas: List[Dict] = []

    for p in files:
        text = _read_text_file(p)
        if not (text or "").strip():
            continue

        rel = str(p.relative_to(DOCS_DIR)).replace("\\", "/")
        sections = _parse_markdown_sections(text)
        if not sections:
            continue

        file_count += 1
        chunk_index = 0

        for s in sections:
            heading_level = s["heading_level"]
            section_title = s["section_title"]
            section_path = s["section_path"]
            body = (s["content"] or "").strip()
            if not body:
                continue

            header = f"# {section_path}\n"
            section_text = (header + body).strip()

            sub_chunks = _chunk_text(section_text, max_chars=900, overlap=120)
            if not sub_chunks:
                continue

            for sub_i, sub_text in enumerate(sub_chunks):
                doc_id = _stable_id(rel, section_path, str(sub_i))
                ids.append(doc_id)
                docs.append(sub_text)
                metas.append(
                    {
                        "source": rel,
                        "type": "md",
                        "chunk_index": chunk_index,
                        "heading_level": heading_level,
                        "section_title": section_title,
                        "section_path": section_path,
                        "sub_index": sub_i,
                    }
                )
                chunk_index += 1
                total_chunks += 1

    if not docs:
        print("[ingest] No markdown sections found in", DOCS_DIR)
        return (0, 0)

    embeddings = embed_texts(docs)

    # 저장(중복 방지)
    try:
        if hasattr(collection, "upsert"):
            collection.upsert(
                ids=ids,
                documents=docs,
                metadatas=metas,
                embeddings=embeddings,
            )
        else:
            # 구버전: delete 후 add
            try:
                collection.delete(ids=ids)
            except Exception:
                pass
            collection.add(
                ids=ids,
                documents=docs,
                metadatas=metas,
                embeddings=embeddings,
            )
    except Exception as e:
        # ingest는 “데이터 생성 배치”이므로 조용히 add로 강행하지 않고 실패를 드러냄
        raise RuntimeError(f"[ingest] failed to write to chroma: {e}") from e

    print(f"[ingest] files={file_count}, chunks={total_chunks}, collection={COLLECTION_NAME}")
    return (file_count, total_chunks)


if __name__ == "__main__":
    ingest()
