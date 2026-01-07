from typing import List, Dict, Any
from backend.logs.parser import parse_line, LogEvent

# “로직 메시지”로 인정할 채널
LOGIC_CHANNELS = {"recvMOS", "sendMOS", "recvEQP", "sendEQP"}


def is_logic_event(ev: LogEvent) -> bool:
    """
    ✅ 로직 이벤트 판정
    - 기본: 채널이 recv/send MOS/EQP 인 메시지만 포함 (Loading... 같은 노이즈 제외)
    - 단, S6F11은 규칙 적용:
        * CEID만 있는 S6F11(설비 이벤트 단순 발생) 제외
        * WORK+CEID가 있는 S6F11(TC 로직 진행)만 포함
    """
    if (ev.channel or "") not in LOGIC_CHANNELS:
        return False

    if not ev.msg_name:
        return False

    if ev.msg_name.upper() == "S6F11":
        return bool(ev.work and ev.ceid)

    # S6F11이 아닌 메시지(TOOL_CONDITION_REPLY 등)는 채널만 맞으면 포함
    return True


def is_error_like(ev: LogEvent) -> bool:
    """
    ✅ 에러 판단: level=ERROR or STATUS=FAIL or Exception 포함
    """
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
        error_msg = e.kv.get("ERRORMSG") or e.kv.get("ERRMSG") or e.kv.get("ERROR") or ""
        timeline.append(
            {
                "ts": e.ts.isoformat(timespec="milliseconds"),
                "eqpid": e.eqpid,
                "carid": e.carid,
                "lotid": e.lotid,
                "msg_name": e.msg_name,
                "channel": e.channel,
                "work": e.work,
                "ceid": e.ceid,
                "status": e.status,
                "error_msg": error_msg,
                "error_like": is_error_like(e),
                "raw": e.raw_msg,
            }
        )

    return {
        "total_lines": len((log_text or "").splitlines()),
        "timeline_count": len(timeline),
        "timeline": timeline,
    }
