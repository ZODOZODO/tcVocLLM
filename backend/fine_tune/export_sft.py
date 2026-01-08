from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable


def _read_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def main() -> None:
    ap = argparse.ArgumentParser(description="Export tcVocLLM traces to SFT JSONL (chat messages format).")
    ap.add_argument("--input", default="./data/traces/agent_chat.jsonl", help="input jsonl")
    ap.add_argument("--output", default="./data/fine_tune/sft.jsonl", help="output jsonl")
    ap.add_argument("--include_system", action="store_true", help="prepend a system message for each sample")
    args = ap.parse_args()

    in_path = Path(args.input)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    system_msg = (
        "당신은 반도체 설비 운영/VOC/로그 트러블슈팅 지원 챗봇입니다. "
        "설명은 한국어로만 작성하고, 근거가 부족하면 추측하지 말고 추가 정보를 요청하세요."
    )

    n = 0
    with out_path.open("w", encoding="utf-8") as out:
        for rec in _read_jsonl(in_path):
            msg = (rec.get("message") or "").strip()
            ans = (rec.get("answer") or "").strip()
            if not msg or not ans:
                continue

            sample = {"messages": []}
            if args.include_system:
                sample["messages"].append({"role": "system", "content": system_msg})

            sample["messages"].append({"role": "user", "content": msg})
            sample["messages"].append({"role": "assistant", "content": ans})

            out.write(json.dumps(sample, ensure_ascii=False) + "\n")
            n += 1

    print(f"wrote {n} samples -> {out_path}")


if __name__ == "__main__":
    main()
