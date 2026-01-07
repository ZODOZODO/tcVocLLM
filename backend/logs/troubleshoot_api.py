from fastapi import APIRouter
from loguru import logger

from backend.logs.troubleshoot_schemas import (
    TroubleshootRecommendRequest,
    TroubleshootRecommendResponse,
    TroubleshootItem,
)
from backend.logs.troubleshoot_service import recommend_troubleshooting

router = APIRouter(prefix="/logs/troubleshoot", tags=["logs-troubleshoot"])


@router.post("/recommend", response_model=TroubleshootRecommendResponse)
def recommend(req: TroubleshootRecommendRequest):
    try:
        query, items, debug = recommend_troubleshooting(
            log_text=req.log_text,
            top_n=req.top_n,
            candidates=req.candidates,
            source=req.source,
        )
        return TroubleshootRecommendResponse(
            query=query,
            items=[TroubleshootItem(**x) for x in items],
            debug=debug,
        )
    except Exception as e:
        logger.exception("troubleshoot recommend failed")
        # 실패 시에도 형태는 유지
        return TroubleshootRecommendResponse(
            query="",
            items=[],
            debug={"error": str(e)},
        )
