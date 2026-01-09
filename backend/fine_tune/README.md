# Fine-tuning workflow (feedback → LoRA → serving)

## Feedback data 구조

`backend/agent/api.py`의 `/agent/feedback` 엔드포인트는 다음 JSONL 구조를 유지합니다.

```json
{"interaction_id":"<uuid>","rating":1,"comment":"optional"}
```

* `interaction_id`: `data/traces/agent_chat.jsonl`에 기록된 대화 트레이스의 ID
* `rating`: -1(부정) / 0(중립) / 1(긍정)
* `comment`: 선택 사항

## 실행 예시

아래 순서로 “feedback 기반 학습 데이터 생성 → LoRA 학습 → 서빙 반영”을 수행합니다.

### 1) feedback 기반 학습 데이터 생성

```bash
python -m backend.fine_tune.export_sft \
  --input ./data/traces/agent_chat.jsonl \
  --feedback ./data/feedback.jsonl \
  --output ./data/fine_tune/sft.jsonl \
  --positive_output ./data/fine_tune/sft_positive.jsonl \
  --negative_output ./data/fine_tune/sft_negative.jsonl \
  --rlhf_output ./data/fine_tune/rlhf.jsonl \
  --dpo_output ./data/fine_tune/dpo.jsonl \
  --min_rating -1 \
  --max_rating 1 \
  --include_system
```

* `rlhf.jsonl`: `{"prompt","response","score","interaction_id","comment"}` 형식
* `dpo.jsonl`: `{"prompt","chosen","rejected","chosen_interaction_id","rejected_interaction_id"}` 형식

### 2) LoRA 학습

```bash
python -m backend.fine_tune.train_lora \
  --train_file ./data/fine_tune/sft.jsonl \
  --output_dir ./data/fine_tune/lora_out
```

### 3) 서빙 반영

* LoRA 어댑터를 사용하는 경우, 서빙 환경에서 base 모델에 LoRA 체크포인트를 로드하도록 설정합니다.
* 전체 모델을 내보낸 경우, 서빙 모델 경로를 `lora_out` 결과물로 교체합니다.
