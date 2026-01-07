import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Dict

# 예시 라인:
# 2026-01-06 00:00:10.114 [TID=00000005][INFO][recvEQP] S6F11 [WORK=S_2000_LOAD CEID=10000] PORTID=1 LPSTATE=LOAD [PROCESS=A_TBLSET02]
LINE_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3})\s+"
    r"\[TID=(?P<tid>[^\]]+)\]\[(?P<level>[^\]]+)\]"
    r"(?:\[(?P<channel>[^\]]+)\])?\s*"
    r"(?P<msg>.*)$"
)

# ✅ 개선: ERRORMSG="PORT STATE IS NOT IDLE" 처럼 공백/따옴표 포함 값을 제대로 잡기
KV_RE = re.compile(r'(?P<k>[A-Z0-9_]+)=(?P<v>"[^"]*"|[^\s\]]+)')

WORK_CEID_RE = re.compile(r"\[WORK=(?P<work>[^ \]]+)\s+CEID=(?P<ceid>\d+)\]")


@dataclass
class LogEvent:
    ts: datetime
    level: str
    channel: str
    raw_msg: str
    eqpid: Optional[str]
    carid: Optional[str]
    lotid: Optional[str]
    msg_name: Optional[str]     # 예: TOOL_CONDITION_REQUEST, S6F11 등
    work: Optional[str]         # WORK=...
    ceid: Optional[str]         # CEID=...
    status: Optional[str]       # STATUS=PASS/FAIL
    has_exception: bool
    kv: Dict[str, str]


def parse_line(line: str) -> Optional[LogEvent]:
    line = (line or "").strip()
    if not line:
        return None

    m = LINE_RE.match(line)
    if not m:
        return None

    ts = datetime.strptime(m.group("ts"), "%Y-%m-%d %H:%M:%S.%f")
    level = (m.group("level") or "").strip()
    channel = (m.group("channel") or "").strip() if m.group("channel") else ""
    msg = (m.group("msg") or "").strip()

    # key=value 파싱 (따옴표 제거)
    kv: Dict[str, str] = {}
    for mm in KV_RE.finditer(msg):
        k = mm.group("k")
        v = mm.group("v") or ""
        if len(v) >= 2 and v[0] == '"' and v[-1] == '"':
            v = v[1:-1]
        kv[k] = v

    eqpid = kv.get("EQPID")
    carid = kv.get("CARID")
    lotid = kv.get("LOTID")
    status = kv.get("STATUS")

    # 메시지명 추정: 맨 앞 토큰(공백 전까지)
    msg_name = msg.split()[0].strip() if msg else None

    # WORK/CEID 추출 (둘 다 있어야 “로직 진행 S6F11”로 인정)
    work = None
    ceid = None
    mc = WORK_CEID_RE.search(msg)
    if mc:
        work = mc.group("work")
        ceid = mc.group("ceid")

    has_exception = ("Exception" in msg) or ("Traceback" in msg)

    return LogEvent(
        ts=ts,
        level=level,
        channel=channel,
        raw_msg=msg,
        eqpid=eqpid,
        carid=carid,
        lotid=lotid,
        msg_name=msg_name,
        work=work,
        ceid=ceid,
        status=status,
        has_exception=has_exception,
        kv=kv,
    )
