from typing import List, Dict, Any, Optional
from datetime import datetime

from backend.logs.parser import parse_line, LogEvent


def is_logic_event(ev: LogEvent) -> bool:
    # ✅ 로직 진행 이벤트: WORK/CEID 둘 다 존재
    return bool(ev.work and ev.ceid)


def is_error_like(ev: LogEvent) -> bool:
    # ✅ 에러 판단: level=ERROR or STATUS=FAIL or Exception 포함
    if (ev.level or "").upper() == "ERROR":
        return True
    if (ev.status or "").upper() == "FAIL":
        return True
    if ev.has_exception:
        return True
    return False


def build_timeline(log_text: str) -> Dict[str, Any]:
    events: List[LogEvent] = []
    for raw in (log_text or "").splitlines():
        ev = parse_line(raw)
        if not ev:
            continue
        if not is_logic_event(ev):
            continue
        events.append(ev)

    # 시간순 정렬(로그가 섞여 들어와도 정렬)
    events.sort(key=lambda e: e.ts)

    timeline: List[Dict[str, Any]] = []
    for e in events:
        timeline.append(
            {
                "ts": e.ts.isoformat(timespec="milliseconds"),
                "eqpid": e.eqpid,
                "carid": e.carid,
                "lotid": e.lotid,
                "msg_name": e.msg_name,
                "work": e.work,
                "ceid": e.ceid,
                "status": e.status,
                "error_like": is_error_like(e),
                "raw": e.raw_msg,
            }
        )

    return {
        "total_lines": len((log_text or "").splitlines()),
        "timeline_count": len(timeline),
        "timeline": timeline,
    }
