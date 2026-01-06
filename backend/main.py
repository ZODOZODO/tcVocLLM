from fastapi import FastAPI

from backend.voc.api import router as voc_router
from backend.logs.api import router as logs_router

app = FastAPI(title="tcVocLLM API", version="0.7.0")

# VOC: 기존 엔드포인트(/health, /chat) 유지
app.include_router(voc_router)

# LOGS: 다음 단계 구현(/logs/*)
app.include_router(logs_router)
