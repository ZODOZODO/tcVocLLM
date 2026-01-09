from fastapi import FastAPI

from backend.voc.api import router as voc_router
from backend.logs.api import router as logs_router
from backend.agent.api import router as agent_router
from backend.llm.router import close_llm_clients

app = FastAPI(title="tcVocLLM API", version="0.8.0")

# VOC: 기존 엔드포인트(/health, /chat) 유지
app.include_router(voc_router)

# LOGS: /logs/*
app.include_router(logs_router)

# AGENT: /agent/*
app.include_router(agent_router)


@app.on_event("shutdown")
def _shutdown():
    # Ollama http client close (agent 전용)
    close_llm_clients()
