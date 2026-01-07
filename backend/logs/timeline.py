# backend/logs/timeline.py
from typing import List, Dict, Any, Optional
from datetime import datetime

from backend.logs.parser import parse_line, LogEvent


def _get_chan(ev: LogEvent) -> str:
    """
    parser 구현에 따라 채널명이 chan/channel/tag 등으로 들어올 수 있어
    최대한 안전하게 접근합니다.
    """
    for k in ("chan", "channel", "io", "direction", "tag"):
        v = getattr(ev, k, None)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _get_level(ev: LogEvent) -> str:
    v = getattr(ev, "level", "") or ""
    return str(v).upper().strip()


def _get_status(ev: LogEvent) -> str:
    v = getattr(ev, "status", "") or ""
    return str(v).upper().strip()


def is_error_like(ev: LogEvent) -> bool:
    """
    ✅ 에러 판단:
    - level=ERROR
    - STATUS=FAIL
    - Exception 포함
    """
    if _get_level(ev) in ("ERROR", "FATAL"):
        return True
    if _get_status(ev) == "FAIL":
        return True
    if bool(getattr(ev, "has_exception", False)):
        return True
    return False


def _is_eqp_s6f11_noise(ev: LogEvent) -> bool:
    """
    ✅ 규칙:
    - S6F11은 설비에서 발생했다는 의미(CEID만 있는 경우)가 있을 수 있음
    - "로직 진행"은 WORK + CEID가 함께 있는 경우로 정의
    - 따라서 recvEQP의 S6F11인데 WORK/CEID가 없으면 제외(단, FAIL/Exception이면 포함)
    """
    chan = _get_chan(ev)
    msg = (getattr(ev, "msg_name", "") or "").strip()
    has_work = bool(getattr(ev, "work", None))
    has_ceid = bool(getattr(ev, "ceid", None))

    if chan == "recvEQP" and msg == "S6F11" and not (has_work and has_ceid):
        return True
    return False


def _should_include(ev: LogEvent) -> bool:
    """
    타임라인 포함 규칙(핵심):
    1) FAIL/ERROR/Exception(=error_like)은 무조건 포함
    2) MOS<->TC / TC<->EQP 로직 메시지는 포함 (WORK/CEID 없어도 포함)
       - 단, recvEQP의 S6F11은 WORK+CEID 없으면 '쓸모없는 이벤트'로 제외
    3) 그 외 채널은 WORK+CEID(로직 진행)인 경우만 포함
    """
    if is_error_like(ev):
        # FAIL/Exception이면, 설비 단순 이벤트라도 운영자가 봐야 하므로 포함
        return True

    # recvEQP S6F11 noise는 제외
    if _is_eqp_s6f11_noise(ev):
        return False

    chan = _get_chan(ev)
    if chan in ("recvMOS", "sendMOS", "sendEQP", "recvEQP"):
        return True

    # fallback: "로직 진행" 정의(WORK/CEID 둘 다)
    has_work = bool(getattr(ev, "work", None))
    has_ceid = bool(getattr(ev, "ceid", None))
    return bool(has_work and has_ceid)


def build_timeline(log_text: str) -> Dict[str, Any]:
    total_lines = len((log_text or "").splitlines())

    events: List[LogEvent] = []
    for raw in (log_text or "").splitlines():
        ev = parse_line(raw)
        if not ev:
            continue
        if not _should_include(ev):
            continue
        events.append(ev)

    # 시간순 정렬(로그가 섞여 들어와도 정렬)
    events.sort(key=lambda e: e.ts)

    timeline: List[Dict[str, Any]] = []
    for e in events:
        timeline.append(
            {
                "ts": e.ts.isoformat(timespec="milliseconds"),
                "eqpid": getattr(e, "eqpid", None),
                "carid": getattr(e, "carid", None),
                "lotid": getattr(e, "lotid", None),
                "msg_name": getattr(e, "msg_name", None),
                "work": getattr(e, "work", None),
                "ceid": getattr(e, "ceid", None),
                "status": getattr(e, "status", None),
                "level": getattr(e, "level", None),
                "chan": _get_chan(e) or None,
                "error_like": is_error_like(e),
                "raw": getattr(e, "raw_msg", None),
            }
        )

    return {
        "total_lines": total_lines,
        "timeline_count": len(timeline),
        "timeline": timeline,
    }
