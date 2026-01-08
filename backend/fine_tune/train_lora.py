from __future__ import annotations

"""
LoRA fine-tuning skeleton.

주의:
- 이 스크립트는 GPU/VRAM 및 추가 패키지(transformers, datasets, peft, accelerate, trl)가 필요합니다.
- 프로젝트 목적은 "데이터 파이프라인/학습 entrypoint" 제공입니다.
"""

import argparse
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--train_file", default="./data/fine_tune/sft.jsonl")
    ap.add_argument("--base_model", default="Qwen/Qwen2.5-7B-Instruct")  # 예시(HF)
    ap.add_argument("--output_dir", default="./data/fine_tune/lora_out")
    args = ap.parse_args()

    from datasets import load_dataset
    from transformers import AutoModelForCausalLM, AutoTokenizer, TrainingArguments
    from transformers import DataCollatorForLanguageModeling
    from trl import SFTTrainer
    from peft import LoraConfig

    data_path = str(Path(args.train_file))
    ds = load_dataset("json", data_files=data_path, split="train")

    tok = AutoTokenizer.from_pretrained(args.base_model, use_fast=True)
    model = AutoModelForCausalLM.from_pretrained(args.base_model, device_map="auto")

    def to_text(example):
        parts = []
        for m in example["messages"]:
            role = m["role"]
            content = m["content"]
            parts.append(f"<{role}>\n{content}\n")
        return {"text": "\n".join(parts).strip()}

    ds = ds.map(to_text, remove_columns=ds.column_names)

    lora = LoraConfig(
        r=8,
        lora_alpha=16,
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
    )

    args_tr = TrainingArguments(
        output_dir=args.output_dir,
        per_device_train_batch_size=1,
        gradient_accumulation_steps=8,
        learning_rate=2e-4,
        num_train_epochs=1,
        logging_steps=10,
        save_steps=200,
        fp16=True,
        report_to=[],
    )

    trainer = SFTTrainer(
        model=model,
        tokenizer=tok,
        train_dataset=ds,
        dataset_text_field="text",
        peft_config=lora,
        args=args_tr,
        data_collator=DataCollatorForLanguageModeling(tok, mlm=False),
        max_seq_length=2048,
    )

    trainer.train()
    trainer.save_model(args.output_dir)
    tok.save_pretrained(args.output_dir)

    print(f"saved -> {args.output_dir}")


if __name__ == "__main__":
    main()
