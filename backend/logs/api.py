from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend.logs.timeline import build_timeline
from backend.logs.troubleshoot import recommend_troubleshooting

router = APIRouter(prefix="/logs", tags=["logs"])


class TimelineRequest(BaseModel):
    log_text: str
    filename: str = ""  # UI 호환(표시용). 비워도 됨


class TroubleshootRequest(BaseModel):
    log_text: str = Field("", description="원본 로그(전체/일부). 비워도 됨")
    filename: str = Field("", description="UI 표시용 파일명(선택)")
    query: str = Field("", description="직접 입력 검색어(선택). 없으면 log_text에서 자동 추출")
    k: int = Field(5, ge=1, le=20, description="추천 개수")


@router.post("/timeline")
def timeline(req: TimelineRequest):
    return build_timeline(req.log_text, filename=req.filename)


@router.post("/troubleshoot")
def troubleshoot(req: TroubleshootRequest):
    return recommend_troubleshooting(log_text=req.log_text, query=req.query, k=req.k)
