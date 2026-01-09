from __future__ import annotations

import os
from importlib.util import find_spec
from typing import Optional, Tuple

HF_MODEL_PATH = os.getenv("HF_MODEL_PATH", "").strip()
LORA_ADAPTER_PATH = os.getenv("LORA_ADAPTER_PATH", "").strip() or None
HF_MAX_NEW_TOKENS = int(os.getenv("HF_MAX_NEW_TOKENS", "1000"))
HF_TEMPERATURE = float(os.getenv("HF_TEMPERATURE", "0.2"))
HF_TOP_P = float(os.getenv("HF_TOP_P", "0.9"))
HF_REPETITION_PENALTY = float(os.getenv("HF_REPETITION_PENALTY", "1.05"))
HF_DEVICE = os.getenv("HF_DEVICE", "auto")
HF_DTYPE = os.getenv("HF_DTYPE", "auto")

_HF_MODEL = None
_HF_TOKENIZER = None


def _resolve_dtype(torch_module):
    if HF_DTYPE in {"auto", ""}:
        return None
    mapping = {
        "float16": torch_module.float16,
        "fp16": torch_module.float16,
        "bfloat16": torch_module.bfloat16,
        "bf16": torch_module.bfloat16,
        "float32": torch_module.float32,
        "fp32": torch_module.float32,
    }
    return mapping.get(HF_DTYPE.lower())


def _ensure_deps() -> Tuple[object, object, object, Optional[object]]:
    missing = [pkg for pkg in ("torch", "transformers") if find_spec(pkg) is None]
    if missing:
        raise RuntimeError(f"HF backend requires missing packages: {', '.join(missing)}")
    if LORA_ADAPTER_PATH and find_spec("peft") is None:
        raise RuntimeError("HF backend requires 'peft' when LORA_ADAPTER_PATH is set")

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    PeftModel = None
    if LORA_ADAPTER_PATH:
        from peft import PeftModel

    return torch, AutoModelForCausalLM, AutoTokenizer, PeftModel


def _load_hf_model() -> Tuple[object, object]:
    global _HF_MODEL, _HF_TOKENIZER

    if _HF_MODEL is not None and _HF_TOKENIZER is not None:
        return _HF_MODEL, _HF_TOKENIZER

    if not HF_MODEL_PATH:
        raise RuntimeError("HF_MODEL_PATH is required when LLM_BACKEND=hf")

    torch, AutoModelForCausalLM, AutoTokenizer, PeftModel = _ensure_deps()

    dtype = _resolve_dtype(torch)
    tokenizer = AutoTokenizer.from_pretrained(HF_MODEL_PATH, use_fast=True)

    if HF_DEVICE == "auto":
        model = AutoModelForCausalLM.from_pretrained(
            HF_MODEL_PATH,
            torch_dtype=dtype,
            device_map="auto",
        )
    else:
        model = AutoModelForCausalLM.from_pretrained(
            HF_MODEL_PATH,
            torch_dtype=dtype,
        )
        model.to(HF_DEVICE)

    if LORA_ADAPTER_PATH:
        model = PeftModel.from_pretrained(model, LORA_ADAPTER_PATH)

    model.eval()

    _HF_MODEL = model
    _HF_TOKENIZER = tokenizer
    return model, tokenizer


def _build_prompt(tokenizer, system_msg: str, user_msg: str, retry_msg: Optional[str]) -> str:
    messages = [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_msg},
    ]
    if retry_msg:
        messages.append({"role": "user", "content": retry_msg})

    if hasattr(tokenizer, "apply_chat_template"):
        return tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)

    prompt = f"[SYSTEM]\n{system_msg}\n\n[USER]\n{user_msg}\n"
    if retry_msg:
        prompt += f"\n[USER]\n{retry_msg}\n"
    prompt += "\n[ASSISTANT]\n"
    return prompt


def call_hf_chat(system_msg: str, user_msg: str, retry_msg: Optional[str] = None) -> str:
    model, tokenizer = _load_hf_model()
    prompt = _build_prompt(tokenizer, system_msg, user_msg, retry_msg)

    inputs = tokenizer(prompt, return_tensors="pt")
    inputs = {k: v.to(model.device) for k, v in inputs.items()}
    input_len = inputs["input_ids"].shape[-1]

    do_sample = HF_TEMPERATURE > 0
    outputs = model.generate(
        **inputs,
        max_new_tokens=HF_MAX_NEW_TOKENS,
        temperature=HF_TEMPERATURE if do_sample else None,
        top_p=HF_TOP_P if do_sample else None,
        do_sample=do_sample,
        repetition_penalty=HF_REPETITION_PENALTY,
    )

    generated = outputs[0][input_len:]
    text = tokenizer.decode(generated, skip_special_tokens=True)
    return (text or "").strip()


def close_hf_model() -> None:
    global _HF_MODEL, _HF_TOKENIZER
    _HF_MODEL = None
    _HF_TOKENIZER = None
