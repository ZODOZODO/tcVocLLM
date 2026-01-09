from __future__ import annotations

import os
from typing import Optional

from backend.llm.hf import call_hf_chat, close_hf_model
from backend.llm.ollama import call_ollama_chat, close_http_client


LLM_BACKEND = os.getenv("LLM_BACKEND", "ollama").strip().lower()


def call_llm_chat(system_msg: str, user_msg: str, retry_msg: Optional[str] = None) -> str:
    backend = os.getenv("LLM_BACKEND", LLM_BACKEND).strip().lower()
    if backend == "ollama":
        return call_ollama_chat(system_msg, user_msg, retry_msg=retry_msg)
    if backend == "hf":
        return call_hf_chat(system_msg, user_msg, retry_msg=retry_msg)
    raise ValueError(f"Unsupported LLM_BACKEND: {backend}")


def close_llm_clients() -> None:
    close_http_client()
    close_hf_model()
