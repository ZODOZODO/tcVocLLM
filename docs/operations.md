# tcVocLLM 운영 설계/체크리스트

본 문서는 **운영 관점**에서 필요한 모니터링/비용/배포/대시보드/체크리스트 설계를 정리합니다.
현재 코드베이스는 JSONL 기반 트레이스 기록 유틸(`backend/telemetry/store.py`)을 제공하므로,
추가적인 APM 없이도 **간단한 JSON 로그 수집**으로 운영을 시작할 수 있습니다.

## 1) 모니터링 설계 (LLM/RAG/리랭커)

### 1-1. LLM 호출 성공률/응답 시간 로그
- 목표 지표
  - LLM 호출 성공률(%), 실패율(%), 평균/중간/95p 응답시간(ms)
  - 호출 타임아웃/에러 타입 분류
- 권장 JSONL 로그 이벤트 예시
  - 파일: `data/traces/llm_calls.jsonl` (TRACE_DIR 기준)
  - 필드 예시
    ```json
    {
      "ts": "2025-01-01T00:00:00Z",
      "event": "llm.call",
      "model": "qwen2.5:7b-instruct-q4_K_M",
      "provider": "ollama",
      "success": true,
      "latency_ms": 1520,
      "prompt_tokens": 1234,
      "completion_tokens": 456,
      "error": null,
      "interaction_id": "..."
    }
    ```

### 1-2. RAG hit rate, reranker 사용률
- 목표 지표
  - RAG hit rate = `hits > 0` 비율
  - 리랭커 사용률 = `rerank_enabled = true` 비율
  - 히트 문서 수/최종 선택 문서 수 분포
- 권장 JSONL 로그 이벤트 예시
  - 파일: `data/traces/rag_retrieval.jsonl`
  - 필드 예시
    ```json
    {
      "ts": "2025-01-01T00:00:00Z",
      "event": "rag.retrieve",
      "query": "...",
      "hits": 5,
      "topk": 3,
      "rerank_enabled": true,
      "rerank_model": "cross-encoder/ms-marco-MiniLM-L-6-v2",
      "latency_ms": 210,
      "interaction_id": "..."
    }
    ```

## 2) 비용 관리 (Ollama 호출/캐시)

### 2-1. Ollama model/embedding 호출 횟수 로그화
- 목표 지표
  - LLM 호출 수, 임베딩 호출 수
  - 모델별 호출 비율
- 권장 JSONL 로그 이벤트 예시
  - 파일: `data/traces/cost_usage.jsonl`
  - 필드 예시
    ```json
    {
      "ts": "2025-01-01T00:00:00Z",
      "event": "ollama.usage",
      "kind": "llm",
      "model": "qwen2.5:7b-instruct-q4_K_M",
      "count": 1,
      "latency_ms": 1520,
      "interaction_id": "..."
    }
    ```

### 2-2. 캐시 hit rate 기록
- 임베딩 캐시 hit/miss 비율 기록
- 권장 JSONL 로그 이벤트 예시
  - 파일: `data/traces/cache.jsonl`
  - 필드 예시
    ```json
    {
      "ts": "2025-01-01T00:00:00Z",
      "event": "embed.cache",
      "key": "sha256:...",
      "hit": true
    }
    ```

## 3) 배포 전략 (Docker/Compose)

> 현재 레포에는 Dockerfile/Compose 파일이 없습니다. 아래는 운영 문서화용 **권장 구성 예시**입니다.

### 3-1. 서비스 구성 (예시)
- `backend`: FastAPI 서버
- `ui`: Streamlit UI
- `ollama`: LLM/Embedding 서버
- `chroma`: Chroma DB (로컬 디스크 사용)

### 3-2. 환경변수 정리
- 공통
  - `TRACE_DIR` (기본: `./data/traces`)
  - `TRACE_ENABLE` (기본: `1`)
- Ollama
  - `OLLAMA_BASE_URL` (기본: `http://127.0.0.1:11434`)
  - `OLLAMA_MODEL` (기본: `qwen2.5:7b-instruct-q4_K_M`)
  - `OLLAMA_EMBED_MODEL` (기본: `nomic-embed-text`)
- RAG/Chroma
  - `DOCS_DIR` (기본: `./data/docs`)
  - `CHROMA_DIR` (기본: `./data/chroma`)
  - `CHROMA_COLLECTION` (기본: `tcvoc_docs`)

### 3-3. 모델 경로/Chroma DB 초기화 절차
1. 문서 폴더 구성: `data/docs/`에 md/txt 문서 저장
2. 임베딩/인덱스 생성
   - 스크립트: `backend/voc/rag/ingest.py`
   - 예: `python backend/voc/rag/ingest.py`
3. Chroma DB 디렉터리 확인
   - 기본 경로: `data/chroma/`
4. 서비스 기동 후 RAG 호출 확인
   - API: `POST /voc/chat` 또는 UI에서 질의

### 3-4. Compose 문서화 템플릿 (초안)
- 서비스 간 네트워크, 볼륨, 환경변수를 포함해 문서화
- 예시 항목
  - `backend` → `CHROMA_DIR`, `DOCS_DIR`, `OLLAMA_BASE_URL`
  - `ollama` → 모델 볼륨 마운트
  - `chroma` → `data/chroma` 볼륨

## 4) 성능/품질 대시보드 설계 (JSON 로그 기반)

### 4-1. 최소 대시보드 지표
- LLM 성공률/평균 응답시간
- RAG hit rate/리랭커 사용률
- 캐시 hit rate
- 오류 유형 상위 TOP N

### 4-2. JSONL 집계 파이프라인 예시
1. `data/traces/*.jsonl` → 배치 집계 스크립트(1분/5분/1시간)
2. 결과를 `data/metrics/*.json`으로 저장
3. Streamlit 또는 간단한 Grafana/Prometheus 연동

### 4-3. 간단 지표 JSON 구조 예시
```json
{
  "ts": "2025-01-01T00:00:00Z",
  "window": "5m",
  "llm": {
    "success_rate": 0.98,
    "p95_latency_ms": 2100
  },
  "rag": {
    "hit_rate": 0.72,
    "rerank_rate": 0.55
  },
  "cache": {
    "embed_hit_rate": 0.63
  }
}
```

## 5) 운영 체크리스트

### 일일 점검
- [ ] API 서버/Streamlit UI 정상 응답 여부
- [ ] `data/traces/` 로그 파일 증가 여부
- [ ] Ollama 서버 상태 확인 (모델 로딩/메모리)
- [ ] 최근 24h 오류율/타임아웃 비율

### 주간 점검
- [ ] RAG hit rate/리랭커 사용률 추이 확인
- [ ] 캐시 hit rate 추이 확인 (하락 시 캐시 무효화/키 전략 점검)
- [ ] Chroma DB 크기/증가율 확인
- [ ] 로그/트레이스 보관 기간 정리(오래된 JSONL 압축/아카이브)

### 배포/변경 시 점검
- [ ] 환경변수 적용 여부 확인
- [ ] `data/docs/` 문서 변경 시 재인덱싱 수행
- [ ] Ollama 모델 버전/태그 확인
- [ ] 샘플 질의로 품질 스모크 테스트
