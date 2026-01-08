from __future__ import annotations

from typing import Any, Dict, List, Literal
from pydantic import BaseModel, Field

AgentMode = Literal["auto", "voc", "logs"]


class AgentRequest(BaseModel):
    message: str = Field("", description="사용자 질문(필수)")
    mode: AgentMode = Field("auto", description="auto|voc|logs")
    log_text: str = Field("", description="원본 로그 텍스트(선택)")
    filename: str = Field("", description="로그 파일명(선택)")
    k: int = Field(5, ge=1, le=20, description="추천/근거 개수")
    include_debug: bool = Field(False, description="steps/중간정보 포함 여부")


class AgentResponse(BaseModel):
    interaction_id: str
    answer: str
    sources: List[Dict[str, Any]] = []
    steps: List[Dict[str, Any]] = []
