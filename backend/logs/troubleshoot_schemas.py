from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any


class TroubleshootRecommendRequest(BaseModel):
    log_text: str = Field(..., description="원본 로그 텍스트(여러 줄 가능)")
    top_n: int = Field(5, ge=1, le=20, description="추천 결과 개수")
    candidates: int = Field(30, ge=5, le=200, description="1차 검색 후보 개수(재랭킹 전)")
    source: str = Field("troubleshooting.md", description="대상 문서(source 메타데이터) 필터")


class TroubleshootItem(BaseModel):
    title: str
    section_path: str
    source: str
    score: float
    distance: Optional[float] = None
    excerpt: str
    meta: Dict[str, Any] = {}


class TroubleshootRecommendResponse(BaseModel):
    query: str
    items: List[TroubleshootItem]
    debug: Dict[str, Any] = {}
