"""
train_lora.py

Supervised Fine-Tuning (SFT) with LoRA/QLoRA using Hugging Face TRL.

- Input dataset: JSONL with either:
  1) conversational format: {"messages":[{"role":"user","content":"..."}, {"role":"assistant","content":"..."}]}
  2) standard LM format: {"text":"..."}  (less recommended for chat models)

This script is intended as a *training entrypoint*.
It requires GPU and extra dependencies, e.g.
  pip install -U "transformers>=4.42" datasets accelerate peft trl bitsandbytes

Example:
  python -m backend.fine_tune.train_lora \
    --train_file ./data/fine_tune/sft.jsonl \
    --base_model Qwen/Qwen2.5-1.5B-Instruct \
    --output_dir ./data/fine_tune/lora_out \
    --epochs 1 --lr 1e-4 --batch 1 --grad_accum 8 \
    --max_length 2048 \
    --assistant_only_loss

QLoRA (4-bit) example:
  python -m backend.fine_tune.train_lora \
    --train_file ./data/fine_tune/sft.jsonl \
    --base_model Qwen/Qwen2.5-7B-Instruct \
    --output_dir ./data/fine_tune/qlora_out \
    --load_in_4bit \
    --epochs 1 --lr 1e-4 --batch 1 --grad_accum 16 \
    --max_length 2048
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import List, Optional

from datasets import load_dataset


def _parse_list(csv: str) -> Optional[List[str]]:
    v = (csv or "").strip()
    if not v:
        return None
    return [x.strip() for x in v.split(",") if x.strip()]


def main() -> None:
    ap = argparse.ArgumentParser()

    ap.add_argument("--train_file", default="./data/fine_tune/sft.jsonl", help="JSONL train file")
    ap.add_argument("--base_model", default="Qwen/Qwen2.5-1.5B-Instruct", help="HF model id or local path")
    ap.add_argument("--output_dir", default="./data/fine_tune/lora_out", help="output dir")

    # Training
    ap.add_argument("--epochs", type=float, default=1.0)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--batch", type=int, default=1)
    ap.add_argument("--grad_accum", type=int, default=8)
    ap.add_argument("--max_length", type=int, default=2048)
    ap.add_argument("--packing", action="store_true", help="pack multiple samples into fixed length blocks")
    ap.add_argument("--logging_steps", type=int, default=10)
    ap.add_argument("--save_steps", type=int, default=200)
    ap.add_argument("--seed", type=int, default=42)

    # Precision
    ap.add_argument("--bf16", action="store_true")
    ap.add_argument("--fp16", action="store_true")

    # Loss masking
    ap.add_argument(
        "--assistant_only_loss",
        action="store_true",
        help="compute loss only on assistant messages (requires compatible chat template)",
    )

    # LoRA
    ap.add_argument("--lora_r", type=int, default=8)
    ap.add_argument("--lora_alpha", type=int, default=16)
    ap.add_argument("--lora_dropout", type=float, default=0.05)
    ap.add_argument(
        "--target_modules",
        default="q_proj,k_proj,v_proj,o_proj,gate_proj,up_proj,down_proj",
        help="comma-separated target modules for LoRA (model dependent)",
    )

    # QLoRA
    ap.add_argument("--load_in_4bit", action="store_true", help="enable 4-bit quantized loading (bitsandbytes)")
    ap.add_argument("--bnb_4bit_compute_dtype", default="bfloat16", choices=["float16", "bfloat16", "float32"])
    ap.add_argument("--bnb_4bit_quant_type", default="nf4", choices=["nf4", "fp4"])
    ap.add_argument("--bnb_4bit_use_double_quant", action="store_true")

    args = ap.parse_args()

    train_path = Path(args.train_file)
    if not train_path.exists():
        raise FileNotFoundError(f"train_file not found: {train_path}")

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # ---- Load dataset (JSONL) ----
    ds = load_dataset("json", data_files=str(train_path), split="train")

    # Determine dataset type
    has_messages = "messages" in ds.column_names
    has_text = "text" in ds.column_names
    if not (has_messages or has_text):
        raise ValueError(
            f"Unsupported dataset columns: {ds.column_names}. "
            "Expected 'messages' (chat) or 'text' (LM)."
        )

    # ---- Model / Tokenizer ----
    from transformers import AutoTokenizer, AutoModelForCausalLM

    model_init_kwargs = {}
    if args.load_in_4bit:
        # QLoRA loading
        from transformers import BitsAndBytesConfig
        import torch

        dtype_map = {
            "float16": torch.float16,
            "bfloat16": torch.bfloat16,
            "float32": torch.float32,
        }
        bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type=args.bnb_4bit_quant_type,
            bnb_4bit_use_double_quant=bool(args.bnb_4bit_use_double_quant),
            bnb_4bit_compute_dtype=dtype_map[args.bnb_4bit_compute_dtype],
        )
        model_init_kwargs["quantization_config"] = bnb_config
        model_init_kwargs["device_map"] = "auto"
    else:
        # Full precision / fp16/bf16 controlled by training args
        model_init_kwargs["device_map"] = "auto"

    tokenizer = AutoTokenizer.from_pretrained(args.base_model, use_fast=True)

    # Safety: ensure pad_token exists (SFT uses padding; fallback to eos_token)
    if tokenizer.pad_token is None:
        if tokenizer.eos_token is None:
            raise ValueError("Tokenizer has no pad_token and no eos_token; cannot pad safely.")
        tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForCausalLM.from_pretrained(args.base_model, **model_init_kwargs)

    # ---- LoRA config ----
    from peft import LoraConfig

    target_modules = _parse_list(args.target_modules)
    peft_config = LoraConfig(
        r=int(args.lora_r),
        lora_alpha=int(args.lora_alpha),
        lora_dropout=float(args.lora_dropout),
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=target_modules,
    )

    # ---- TRL SFTTrainer ----
    # TRL 문서 기준: args=SFTConfig(...) 사용
    from trl import SFTTrainer, SFTConfig

    # Dataset field: conversational이면 자동으로 chat template 적용
    sft_args = SFTConfig(
        output_dir=str(out_dir),
        num_train_epochs=float(args.epochs),
        learning_rate=float(args.lr),
        per_device_train_batch_size=int(args.batch),
        gradient_accumulation_steps=int(args.grad_accum),
        logging_steps=int(args.logging_steps),
        save_steps=int(args.save_steps),
        seed=int(args.seed),
        bf16=bool(args.bf16),
        fp16=bool(args.fp16),
        max_length=int(args.max_length),
        packing=bool(args.packing),
        assistant_only_loss=bool(args.assistant_only_loss),
        report_to=[],  # W&B 등 자동 리포팅 방지
    )

    # dataset_text_field는 text 기반일 때만 의미가 큼
    # messages 기반이면 TRL이 대화 포맷을 인식해 처리
    if has_text and not has_messages:
        sft_args.dataset_text_field = "text"

    trainer = SFTTrainer(
        model=model,
        args=sft_args,
        train_dataset=ds,
        processing_class=tokenizer,
        peft_config=peft_config,
    )

    trainer.train()
    trainer.save_model(str(out_dir))
    tokenizer.save_pretrained(str(out_dir))

    print(f"Done. Saved adapter/model artifacts to: {out_dir}")


if __name__ == "__main__":
    main()
