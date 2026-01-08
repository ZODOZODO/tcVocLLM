from __future__ import annotations

from typing import Any, Dict, List, Optional

from backend.logs.parser import parse_line


def is_logic_event(ev: Any) -> bool:
    work = (getattr(ev, "work", "") or "").strip()
    ceid = (getattr(ev, "ceid", "") or "").strip()
    return bool(work and ceid)


def is_error_like(ev: Any) -> bool:
    """
    에러 후보 기준:
    - level=ERROR
    - 또는 STATUS=FAIL
    - 또는 Exception/Traceback 포함
    """
    kv = getattr(ev, "kv", {}) or {}

    level = (getattr(ev, "level", "") or kv.get("level") or kv.get("LEVEL") or "").upper()
    if level == "ERROR":
        return True

    status = (getattr(ev, "status", "") or kv.get("STATUS") or kv.get("status") or "").upper()
    if status == "FAIL":
        return True

    raw = (getattr(ev, "raw", "") or kv.get("raw") or "")  # parser가 raw를 넣을 수도/안 넣을 수도
    # build_timeline에서 원문 라인을 별도로 주입하므로 여기서는 보수적으로만 체크
    if isinstance(raw, str):
        up = raw.upper()
        if "TRACEBACK" in up or "EXCEPTION" in up:
            return True

    # ERRORMSG/ERRMSG가 있으면 에러 후보로 간주
    if (kv.get("ERRORMSG") or kv.get("ERRMSG")):
        return True

    return False


def build_timeline(log_text: str, filename: str = "") -> Dict[str, Any]:
    """
    타임라인 정책:
    - 로직 진행 이벤트: WORK+CEID 동시 존재
    - 에러/FAIL 이벤트: WORK/CEID 없어도 포함
    - 단순 CEID-only 이벤트는 제외(에러/FAIL이면 포함)
    """
    lines = (log_text or "").splitlines()
    out: List[Dict[str, Any]] = []

    for raw_line in lines:
        ev = parse_line(raw_line)
        if not ev:
            continue

        kv = getattr(ev, "kv", {}) or {}

        err_like = is_error_like(ev)
        logic = is_logic_event(ev)

        # 포함 조건: 로직 이벤트 OR 에러 후보
        if not (logic or err_like):
            continue

        def g(attr: str, default: str = "") -> str:
            v = getattr(ev, attr, None)
            if v is None:
                return default
            return str(v)

        status = (g("status") or kv.get("STATUS") or kv.get("status") or "")
        error_msg = (kv.get("ERRORMSG") or kv.get("ERRMSG") or "")

        item = {
            "ts": g("ts", ""),
            "eqpid": g("eqpid", kv.get("EQPID", "") or ""),
            "work": g("work", ""),
            "ceid": g("ceid", ""),
            "direction": g("direction", kv.get("DIR", "") or ""),
            "message": g("msg_name", kv.get("MSG", "") or kv.get("MSGNAME", "") or ""),
            "status": status,
            "error_like": bool(err_like),
            "carid": g("carid", kv.get("CARID", "") or ""),
            "lotid": g("lotid", kv.get("LOTID", "") or ""),
            "error_msg": error_msg,
            "raw": raw_line,
        }
        out.append(item)

    return {
        "filename": filename,
        "total_lines": len(lines),
        "timeline": out,
    }
