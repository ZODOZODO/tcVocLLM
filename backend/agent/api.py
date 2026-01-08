from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend.agent.agent import run_agent
from backend.agent.schemas import AgentRequest, AgentResponse
from backend.telemetry.store import append_jsonl

router = APIRouter(prefix="/agent", tags=["agent"])


class FeedbackRequest(BaseModel):
    interaction_id: str = Field(..., description="agent/chat 응답의 interaction_id")
    rating: int = Field(..., ge=-1, le=1, description="-1(나쁨) / 0(중립) / 1(좋음)")
    comment: str = Field("", description="추가 코멘트(선택)")


@router.post("/chat", response_model=AgentResponse)
def agent_chat(req: AgentRequest):
    data = run_agent(
        message=req.message,
        mode=req.mode,
        log_text=req.log_text,
        filename=req.filename,
        k=req.k,
        include_debug=req.include_debug,
    )
    return AgentResponse(**data)


@router.post("/feedback")
def agent_feedback(req: FeedbackRequest):
    append_jsonl(
        "feedback.jsonl",
        {
            "interaction_id": req.interaction_id,
            "rating": req.rating,
            "comment": req.comment,
        },
    )
    return {"ok": True}
