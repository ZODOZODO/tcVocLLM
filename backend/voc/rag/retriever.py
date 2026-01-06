import os
import re
from typing import Any, Dict, List, Tuple, Optional, DefaultDict
from collections import defaultdict

import chromadb
from dotenv import load_dotenv

from backend.voc.rag.embeddings import embed_texts

load_dotenv()

CHROMA_DIR = os.getenv("CHROMA_DIR", "./data/chroma")
COLLECTION_NAME = os.getenv("CHROMA_COLLECTION", "tcvoc_docs")

# 후보를 얼마나 넉넉히 뽑을지(정확도 향상용)
CAND_MIN = int(os.getenv("RETRIEVE_CAND_MIN", "80"))
CAND_MULT = int(os.getenv("RETRIEVE_CAND_MULT", "20"))

# 같은 섹션(section_path)에서 최대 몇 개 청크까지 허용할지
MAX_PER_SECTION = int(os.getenv("RETRIEVE_MAX_PER_SECTION", "3"))

# 절차(-> 라인)가 많은 섹션이면 같은 섹션 청크를 더 담아 연속성을 확보
ARROW_EXPAND_THRESHOLD = int(os.getenv("RETRIEVE_ARROW_EXPAND_THRESHOLD", "6"))
ARROW_EXPAND_MAX = int(os.getenv("RETRIEVE_ARROW_EXPAND_MAX", "6"))

# ✅ 매 요청마다 만들지 않고 1회 생성(성능/안정성)
_client = chromadb.PersistentClient(path=CHROMA_DIR)
_col = _client.get_or_create_collection(name=COLLECTION_NAME)


def _tokens(query: str) -> List[str]:
    """
    약어/코드/에러 대응을 위해 영문/숫자 토큰을 우선 보존.
    예: APC, CEID, S6F11, WORK_START_REQUEST
    """
    q = (query or "").strip()
    if not q:
        return []
    toks = re.findall(r"[A-Za-z0-9_]+|[가-힣]+", q)
    toks = [t for t in toks if len(t) >= 2]
    # 약어 일치에 유리하도록 대문자화(한글은 변화 없음)
    return list(dict.fromkeys([t.upper() for t in toks]))


def _is_alnum_token(t: str) -> bool:
    return bool(re.fullmatch(r"[A-Z0-9_]+", t or ""))


def _count_arrow_lines(text: str) -> int:
    if not text:
        return 0
    # 단순히 "->" 포함 라인 수로 절차성 판단(질문 하드코딩 아님, 문서 형태 기반)
    return sum(1 for line in text.splitlines() if "->" in line)


def retrieve(query: str, k: int = 6) -> List[Dict[str, Any]]:
    q = (query or "").strip()
    if not q:
        return []

    q_emb = embed_texts([q])[0]

    n_results = max(k * CAND_MULT, CAND_MIN)
    res = _col.query(
        query_embeddings=[q_emb],
        n_results=n_results,
        include=["documents", "metadatas", "distances"],
    )

    docs = (res.get("documents") or [[]])[0]
    metas = (res.get("metadatas") or [[]])[0]
    dists = (res.get("distances") or [[]])[0]

    items: List[Dict[str, Any]] = []
    for doc, meta, dist in zip(docs, metas, dists):
        meta = meta or {}
        items.append({"document": doc or "", "metadata": meta, "distance": dist})

    toks = _tokens(q)

    # ---- Lexical scoring (정확 일치 우선 + 제목/경로 가중) ----
    # 영문/숫자 토큰은 경계 기반 매칭(오탐 감소)
    # 한글 토큰은 substring 허용(형태소 단위 분리까지는 MVP 범위를 넘음)
    def _match_counts(it: Dict[str, Any]) -> Tuple[int, int, int, int]:
        meta = it["metadata"]
        text_u = (it["document"] or "").upper()
        title_u = (meta.get("section_title") or "").upper()
        path_u = (meta.get("section_path") or "").upper()

        exact = 0
        hit_title = 0
        hit_path = 0
        hit_body = 0

        for t in toks:
            if _is_alnum_token(t):
                # 경계 기반: 앞뒤가 [A-Z0-9_]가 아니어야 함
                pat = re.compile(rf"(?<![A-Z0-9_]){re.escape(t)}(?![A-Z0-9_])")
                in_title = bool(pat.search(title_u))
                in_path = bool(pat.search(path_u))
                in_body = bool(pat.search(text_u))
            else:
                in_title = t in title_u
                in_path = t in path_u
                in_body = t in text_u

            if in_title or in_path or in_body:
                # exact는 "영문/숫자 토큰의 경계 매치"만 점수로 강하게 반영
                if _is_alnum_token(t) and (in_title or in_path or in_body):
                    exact += 1
                if in_title:
                    hit_title += 1
                if in_path:
                    hit_path += 1
                if in_body:
                    hit_body += 1

        return exact, hit_title, hit_path, hit_body

    def _rank_key(it: Dict[str, Any]) -> Tuple[int, int, float]:
        exact, hit_title, hit_path, hit_body = _match_counts(it)
        lexical = hit_title * 5 + hit_path * 3 + hit_body * 1
        dist = float(it.get("distance", 1e9))
        # exact 높은 것 우선, lexical 높은 것 우선, distance 작은 것 우선
        return (-exact, -lexical, dist)

    # 토큰이 있으면 lexical 강화 정렬, 없으면 distance 위주 정렬
    if toks:
        items.sort(key=_rank_key)
    else:
        items.sort(key=lambda it: float(it.get("distance", 1e9)))

    # ---- 섹션 단위 과도한 dedup 완화: 섹션당 최대 N개 ----
    picked: List[Dict[str, Any]] = []
    per_section: DefaultDict[str, int] = defaultdict(int)

    def _section_key(it: Dict[str, Any]) -> str:
        meta = it["metadata"]
        return meta.get("section_path") or f'{meta.get("source","unknown")}::{meta.get("chunk_index",-1)}'

    for it in items:
        sk = _section_key(it)
        if per_section[sk] >= MAX_PER_SECTION:
            continue
        picked.append(it)
        per_section[sk] += 1
        if len(picked) >= max(k, 12):  # 후속 확장 여지 확보
            break

    # ---- 절차(->)가 많은 섹션이면 같은 섹션 청크를 추가 확보(연속성 강화) ----
    # 질문 하드코딩이 아니라 "상위 문서가 절차형인지"를 보고 보강
    if picked:
        top = picked[0]
        top_key = _section_key(top)

        # 현재 picked에서 top 섹션이 가진 arrow 라인 총량 추정
        arrow_sum = sum(_count_arrow_lines(it["document"]) for it in picked if _section_key(it) == top_key)

        if arrow_sum >= ARROW_EXPAND_THRESHOLD:
            # 원본 items에서 같은 섹션 청크를 더 가져오되, chunk_index 순으로 정렬해서 추가
            same_section = [it for it in items if _section_key(it) == top_key]
            # chunk_index 기반 정렬(없으면 dist)
            def _chunk_order(it: Dict[str, Any]) -> Tuple[int, float]:
                meta = it["metadata"]
                ci = meta.get("chunk_index", 10**9)
                try:
                    ci = int(ci)
                except Exception:
                    ci = 10**9
                return (ci, float(it.get("distance", 1e9)))

            same_section.sort(key=_chunk_order)

            # picked에 없는 것만 추가
            existing_ids = set()
            for it in picked:
                meta = it["metadata"]
                # ingest에서 stable id를 쓰지만 retriever에서는 id를 include하지 않았으므로
                # document+chunk_index 조합으로 대체(충분히 실용적)
                existing_ids.add((meta.get("section_path"), meta.get("chunk_index"), meta.get("sub_index")))

            added = 0
            for it in same_section:
                meta = it["metadata"]
                key_trip = (meta.get("section_path"), meta.get("chunk_index"), meta.get("sub_index"))
                if key_trip in existing_ids:
                    continue
                picked.append(it)
                existing_ids.add(key_trip)
                added += 1
                if added >= ARROW_EXPAND_MAX:
                    break

    # 최종은 k개만 반환
    return picked[:k]
