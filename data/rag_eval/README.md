# RAG 평가셋 형식

`queries.jsonl`은 한 줄에 하나의 JSON 객체를 담는 JSONL 파일입니다. 각 줄에는 아래 필드를 포함합니다.

- `id`: 평가 항목 식별자 (문자열, 선택)
- `query`: 검색 질의 (문자열, 필수)
- `relevant_section_paths`: 정답 섹션 경로 목록 (문자열 배열, 권장)
- `keywords`: 정답 판단에 사용할 키워드 목록 (문자열 배열, 선택)

`relevant_section_paths`는 ingest 시 `section_path` 메타데이터와 동일한 값이어야 합니다. 예: `추가 자료 및 정보 > SECS/GEM`.

예시:

```json
{"id":"glossary_secs_gem","query":"SECS/GEM의 의미는?","relevant_section_paths":["추가 자료 및 정보 > SECS/GEM"],"keywords":["SECS","GEM"]}
```
