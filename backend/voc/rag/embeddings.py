import os
import json
import time
import hashlib
from pathlib import Path
from typing import List, Dict, Optional
from threading import Lock

import httpx
from dotenv import load_dotenv
from loguru import logger
from concurrent.futures import ThreadPoolExecutor, as_completed

load_dotenv()

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")

# 성능/안정성 튜닝
EMBED_TIMEOUT = float(os.getenv("EMBED_TIMEOUT", "120"))
EMBED_MAX_WORKERS = int(os.getenv("EMBED_MAX_WORKERS", "6"))
EMBED_RETRIES = int(os.getenv("EMBED_RETRIES", "2"))
EMBED_RETRY_BACKOFF = float(os.getenv("EMBED_RETRY_BACKOFF", "0.8"))

# 디스크 캐시(재인제스트 성능 향상)
CACHE_DIR = Path(os.getenv("EMBED_CACHE_DIR", "./data/embed_cache"))
CACHE_DIR.mkdir(parents=True, exist_ok=True)
CACHE_PATH = CACHE_DIR / f"{OLLAMA_EMBED_MODEL.replace(':', '_')}.jsonl"

# 프로세스 내 캐시(1회 로드 후 계속 재사용)
_CACHE: Optional[Dict[str, List[float]]] = None
_CACHE_LOCK = Lock()


def _key_for_text(text: str) -> str:
    raw = (text or "").encode("utf-8", errors="ignore")
    return hashlib.sha1(raw).hexdigest()


def _load_cache_from_disk() -> Dict[str, List[float]]:
    cache: Dict[str, List[float]] = {}
    if not CACHE_PATH.exists():
        return cache
    try:
        with CACHE_PATH.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                k = obj.get("k")
                v = obj.get("v")
                if isinstance(k, str) and isinstance(v, list) and v:
                    cache[k] = v
    except Exception as e:
        logger.warning(f"[embed_cache] load failed: {e}")
    return cache


def _get_cache() -> Dict[str, List[float]]:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    with _CACHE_LOCK:
        if _CACHE is None:
            _CACHE = _load_cache_from_disk()
    return _CACHE


def _append_cache(items: Dict[str, List[float]]) -> None:
    if not items:
        return
    try:
        with CACHE_PATH.open("a", encoding="utf-8") as f:
            for k, v in items.items():
                f.write(json.dumps({"k": k, "v": v}, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning(f"[embed_cache] append failed: {e}")


def _embed_one(client: httpx.Client, text: str) -> List[float]:
    last_err: Optional[Exception] = None
    for attempt in range(EMBED_RETRIES + 1):
        try:
            r = client.post(
                f"{OLLAMA_BASE_URL}/api/embeddings",
                json={"model": OLLAMA_EMBED_MODEL, "prompt": text},
            )
            r.raise_for_status()
            data = r.json()
            emb = data.get("embedding")
            if not isinstance(emb, list) or not emb:
                raise ValueError("embedding missing/empty")
            return emb
        except Exception as e:
            last_err = e
            if attempt < EMBED_RETRIES:
                time.sleep(EMBED_RETRY_BACKOFF * (2 ** attempt))
            else:
                break
    raise last_err or RuntimeError("embedding failed")


def embed_texts(texts: List[str]) -> List[List[float]]:
    """
    Ollama embeddings API로 텍스트 리스트를 임베딩 벡터 리스트로 변환.

    개선사항:
    - 디스크 캐시 + 프로세스 메모리 캐시: 동일 텍스트 재임베딩 방지
    - 동시 처리: ingest 속도 개선
    - 재시도: 일시 오류 안정화
    """
    texts = [t or "" for t in texts]
    if not texts:
        return []

    cache = _get_cache()
    out: List[Optional[List[float]]] = [None] * len(texts)

    # 캐시 히트 선반영
    missing_idx: List[int] = []
    missing_texts: List[str] = []
    missing_keys: List[str] = []

    for i, t in enumerate(texts):
        k = _key_for_text(t)
        v = cache.get(k)
        if v is not None:
            out[i] = v
        else:
            missing_idx.append(i)
            missing_texts.append(t)
            missing_keys.append(k)

    # 전부 캐시에 있으면 순서 그대로 반환
    if not missing_texts:
        return [v for v in out if v is not None]  # type: ignore

    newly_cached: Dict[str, List[float]] = {}

    with httpx.Client(timeout=EMBED_TIMEOUT) as client:
        with ThreadPoolExecutor(max_workers=EMBED_MAX_WORKERS) as ex:
            futures = {}
            for idx, t, k in zip(missing_idx, missing_texts, missing_keys):
                futures[ex.submit(_embed_one, client, t)] = (idx, k)

            first_dim_logged = False

            for fut in as_completed(futures):
                idx, k = futures[fut]
                emb = fut.result()
                out[idx] = emb
                newly_cached[k] = emb

                if not first_dim_logged:
                    first_dim_logged = True
                    logger.info(f"[embed] model={OLLAMA_EMBED_MODEL} dim={len(emb)} (first result)")

    # 메모리 캐시 업데이트 + 디스크 append
    with _CACHE_LOCK:
        cache.update(newly_cached)
    _append_cache(newly_cached)

    if any(v is None for v in out):
        raise RuntimeError("some embeddings are missing after processing")

    return out  # type: ignore


def embed_query(text: str) -> List[float]:
    return embed_texts([text])[0]
