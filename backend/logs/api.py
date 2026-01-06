from fastapi import APIRouter
from pydantic import BaseModel

from backend.logs.timeline import build_timeline

router = APIRouter(prefix="/logs", tags=["logs"])


class TimelineRequest(BaseModel):
    log_text: str


@router.post("/timeline")
def timeline(req: TimelineRequest):
    return build_timeline(req.log_text)
