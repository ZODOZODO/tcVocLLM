# CI/로컬 실행 가이드

## RAG 평가 실행 방법

1. 문서 임베딩이 준비되어 있는지 확인합니다.
   - 필요 시 ingest 실행: `python -m backend.voc.rag.ingest`
2. 평가셋을 준비합니다.
   - `data/rag_eval/queries.jsonl`에 질의/정답 섹션 경로를 입력합니다.
3. 평가 실행:
   - `python -m backend.voc.rag.eval --queries data/rag_eval/queries.jsonl --output data/rag_eval/results.json`

결과는 `data/rag_eval/results.json`에 저장됩니다. `CHROMA_DIR`, `CHROMA_COLLECTION` 환경변수로 컬렉션 경로와 이름을 변경할 수 있습니다.
