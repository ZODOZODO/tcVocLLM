# tcVocLLM Serving Guide

## 서빙 전략

### (A) Ollama 모델로 내보내기
- **권장 상황**: 경량 운영, 단순 배포, Ollama만 사용하고 싶을 때.
- **개요**: LoRA 학습 결과를 베이스 모델에 병합하거나 GGUF로 변환해 Ollama 모델로 등록한 뒤 `OLLAMA_MODEL`로 호출합니다.

### (B) Hugging Face 로컬 모델 서빙
- **권장 상황**: LoRA 어댑터를 그대로 유지하거나, 로컬 경로/HF Hub 모델을 직접 쓰고 싶을 때.
- **개요**: `LLM_BACKEND=hf`로 스위치하고 `HF_MODEL_PATH`와 `LORA_ADAPTER_PATH`로 로컬 모델/어댑터를 지정합니다.

## 환경변수 설계

| 변수 | 설명 | 기본값 |
| --- | --- | --- |
| `LLM_BACKEND` | LLM 백엔드 선택 (`ollama` 또는 `hf`) | `ollama` |
| `OLLAMA_BASE_URL` | Ollama API 주소 | `http://127.0.0.1:11434` |
| `OLLAMA_MODEL` | Ollama 모델 이름 | `qwen2.5:7b-instruct-q4_K_M` |
| `OLLAMA_TEMPERATURE` | Ollama temperature | `0.2` |
| `OLLAMA_NUM_PREDICT` | Ollama max tokens | `1000` |
| `OLLAMA_TIMEOUT` | Ollama 요청 타임아웃(초) | `240` |
| `HF_MODEL_PATH` | HF 로컬 모델 경로 또는 HF Hub ID | 없음 |
| `LORA_ADAPTER_PATH` | LoRA 어댑터 경로(선택) | 없음 |
| `HF_DEVICE` | `auto` 또는 `cpu`/`cuda` 등 | `auto` |
| `HF_DTYPE` | `auto`, `float16`, `bfloat16`, `float32` | `auto` |
| `HF_MAX_NEW_TOKENS` | HF 생성 토큰 수 | `1000` |
| `HF_TEMPERATURE` | HF temperature | `0.2` |
| `HF_TOP_P` | HF top-p | `0.9` |
| `HF_REPETITION_PENALTY` | HF repetition penalty | `1.05` |

## 학습 → 서빙 반영 절차

### 1) LoRA 학습
```bash
python -m backend.fine_tune.train_lora \
  --train_file ./data/fine_tune/sft.jsonl \
  --base_model Qwen/Qwen2.5-1.5B-Instruct \
  --output_dir ./data/fine_tune/lora_out
```

### 2-A) Ollama 서빙으로 반영 (전략 A)
1. LoRA 어댑터를 베이스 모델에 병합하거나 GGUF로 변환합니다.
   - 예: `llama.cpp`의 `convert.py`/`merge_lora.py` 등을 사용.
2. Ollama 모델 등록
   ```bash
   # Modelfile 예시
   FROM ./models/qwen2.5-7b-instruct.gguf
   PARAMETER temperature 0.2
   ```
   ```bash
   ollama create tc-voc-merged -f Modelfile
   ```
3. 환경변수 설정
   ```bash
   export LLM_BACKEND=ollama
   export OLLAMA_MODEL=tc-voc-merged
   ```

### 2-B) HF 로컬 서빙으로 반영 (전략 B)
1. LoRA 어댑터를 그대로 유지 (병합 불필요).
2. 환경변수 설정
   ```bash
   export LLM_BACKEND=hf
   export HF_MODEL_PATH=./models/qwen2.5-7b-instruct
   export LORA_ADAPTER_PATH=./data/fine_tune/lora_out
   ```
3. 필요 패키지 설치
   ```bash
   pip install -U transformers torch peft
   ```

## 실행 예시
```bash
export LLM_BACKEND=ollama
export OLLAMA_MODEL=qwen2.5:7b-instruct-q4_K_M
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

```bash
export LLM_BACKEND=hf
export HF_MODEL_PATH=./models/qwen2.5-7b-instruct
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```
