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

# ✅ 보완: 일부 로그는 [TID=...]가 없거나, timestamp에 .mmm이 없을 수 있음
ALT_LINE_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d{3})?)\s+(?P<rest>.*)$"
)

LEVEL_IN_BRACKET_RE = re.compile(r"\[(TRACE|DEBUG|INFO|WARN|WARNING|ERROR|FATAL)\]", re.IGNORECASE)

# ✅ 개선: ERRORMSG="PORT STATE IS NOT IDLE" 처럼 공백/따옴표 포함 값을 제대로 잡기
# ✅ 보완: status=FAIL 같이 소문자 key도 흡수
KV_RE = re.compile(r'(?P<k>[A-Za-z0-9_]+)=(?P<v>"[^"]*"|[^\s\]]+)')

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

    def _parse_ts(ts_s: str) -> Optional[datetime]:
        ts_s = (ts_s or "").strip()
        if not ts_s:
            return None
        # 밀리초 포함 / 미포함 모두 허용
        for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(ts_s, fmt)
            except Exception:
                continue
        return None

    m = LINE_RE.match(line)
    if m:
        ts = _parse_ts(m.group("ts"))
        if ts is None:
            return None
        level = (m.group("level") or "").strip()
        channel = (m.group("channel") or "").strip() if m.group("channel") else ""
        msg = (m.group("msg") or "").strip()
    else:
        # fallback: 유사한 timestamp 프리픽스만 있는 라인
        ma = ALT_LINE_RE.match(line)
        if not ma:
            return None

        ts = _parse_ts(ma.group("ts"))
        if ts is None:
            return None

        rest = (ma.group("rest") or "").strip()

        # level 추정: [INFO] 같은 토큰을 탐지
        level_m = LEVEL_IN_BRACKET_RE.search(rest)
        level = (level_m.group(1) if level_m else "").upper()

        # channel은 표준화가 어려워서 MVP에서는 비움
        channel = ""

        # msg는 rest 전체(=추가 kv 파싱 가능)
        msg = rest

    # key=value 파싱 (따옴표 제거)
    kv: Dict[str, str] = {}
    for mm in KV_RE.finditer(msg):
        k = (mm.group("k") or "").upper()
        v = mm.group("v") or ""
        if len(v) >= 2 and v[0] == '"' and v[-1] == '"':
            v = v[1:-1]
        kv[k] = v

    eqpid = kv.get("EQPID")
    carid = kv.get("CARID")
    lotid = kv.get("LOTID")
    status = kv.get("STATUS")

    # 메시지명 추정: 맨 앞 토큰(공백 전까지)
    # fallback 라인의 경우 "[TID=..][INFO]" 같은 prefix가 있을 수 있으므로 제거
    tmp = msg or ""
    for _ in range(4):
        if tmp.startswith("[") and "]" in tmp:
            tmp = tmp.split("]", 1)[1].lstrip()
        else:
            break
    msg_name = tmp.split()[0].strip() if tmp else None

    # WORK/CEID 추출 (둘 다 있어야 “로직 진행 S6F11”로 인정)
    work = None
    ceid = None
    mc = WORK_CEID_RE.search(msg)
    if mc:
        work = mc.group("work")
        ceid = mc.group("ceid")

    up_msg = msg.upper()
    has_exception = ("EXCEPTION" in up_msg) or ("TRACEBACK" in up_msg)

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
