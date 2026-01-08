from __future__ import annotations

import os
from typing import Any, Dict, Optional

import httpx
from dotenv import load_dotenv

load_dotenv()

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct-q4_K_M")
OLLAMA_TEMPERATURE = float(os.getenv("OLLAMA_TEMPERATURE", "0.2"))
OLLAMA_NUM_PREDICT = int(os.getenv("OLLAMA_NUM_PREDICT", "1000"))
OLLAMA_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", "240"))

_http = httpx.Client(timeout=OLLAMA_TIMEOUT)


def close_http_client() -> None:
    try:
        _http.close()
    except Exception:
        pass


def call_ollama_chat(system_msg: str, user_msg: str, retry_msg: Optional[str] = None) -> str:
    """Call Ollama /api/chat (non-stream)."""
    messages = [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_msg},
    ]
    if retry_msg:
        messages.append({"role": "user", "content": retry_msg})

    r = _http.post(
        f"{OLLAMA_BASE_URL}/api/chat",
        json={
            "model": OLLAMA_MODEL,
            "stream": False,
            "messages": messages,
            "options": {
                "temperature": OLLAMA_TEMPERATURE,
                "num_predict": OLLAMA_NUM_PREDICT,
            },
        },
    )
    r.raise_for_status()
    data: Dict[str, Any] = r.json()
    return ((data.get("message") or {}).get("content") or "").strip()
