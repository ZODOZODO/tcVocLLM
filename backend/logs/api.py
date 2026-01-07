from fastapi import APIRouter
from pydantic import BaseModel

from backend.logs.timeline import build_timeline
from backend.logs.troubleshoot import recommend_troubleshooting

router = APIRouter(prefix="/logs", tags=["logs"])


class TimelineRequest(BaseModel):
    log_text: str


class TroubleshootRequest(BaseModel):
    query: str
    k: int = 5


@router.post("/timeline")
def timeline(req: TimelineRequest):
    return build_timeline(req.log_text)


@router.post("/troubleshoot")
def troubleshoot(req: TroubleshootRequest):
    return recommend_troubleshooting(req.query, k=req.k)
