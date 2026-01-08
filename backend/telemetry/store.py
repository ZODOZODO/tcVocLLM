from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from dotenv import load_dotenv

load_dotenv()

TRACE_DIR = os.getenv("TRACE_DIR", "./data/traces")
ENABLE_TRACE = os.getenv("TRACE_ENABLE", "1").strip() in ("1", "true", "True", "TRUE")

_lock = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_jsonl(filename: str, record: Dict[str, Any]) -> None:
    """Append a record to TRACE_DIR/filename as JSONL."""
    if not ENABLE_TRACE:
        return

    p = Path(TRACE_DIR)
    p.mkdir(parents=True, exist_ok=True)
    fp = p / filename

    record = dict(record)
    record.setdefault("ts", _now_iso())

    line = json.dumps(record, ensure_ascii=False)
    with _lock:
        with fp.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
