from __future__ import annotations

import argparse
import json
from pathlib import Path
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional


def _read_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def _system_message() -> str:
    return (
        "당신은 반도체 설비 운영/VOC/로그 트러블슈팅 지원 챗봇입니다. "
        "설명은 한국어로만 작성하고, 근거가 부족하면 추측하지 말고 추가 정보를 요청하세요."
    )


def _build_sft_sample(message: str, answer: str, include_system: bool) -> Dict[str, Any]:
    sample = {"messages": []}
    if include_system:
        sample["messages"].append({"role": "system", "content": _system_message()})
    sample["messages"].append({"role": "user", "content": message})
    sample["messages"].append({"role": "assistant", "content": answer})
    return sample


def _index_traces(path: Path) -> Dict[str, Dict[str, Any]]:
    traces: Dict[str, Dict[str, Any]] = {}
    for rec in _read_jsonl(path):
        interaction_id = (rec.get("interaction_id") or "").strip()
        if not interaction_id:
            continue
        traces[interaction_id] = rec
    return traces


def _index_feedback(path: Path) -> Dict[str, Dict[str, Any]]:
    feedback: Dict[str, Dict[str, Any]] = {}
    for rec in _read_jsonl(path):
        interaction_id = (rec.get("interaction_id") or "").strip()
        if not interaction_id:
            continue
        feedback[interaction_id] = {
            "interaction_id": interaction_id,
            "rating": rec.get("rating"),
            "comment": rec.get("comment", ""),
        }
    return feedback


def _join_traces_feedback(
    traces: Dict[str, Dict[str, Any]],
    feedback: Dict[str, Dict[str, Any]],
    require_feedback: bool,
) -> List[Dict[str, Any]]:
    joined: List[Dict[str, Any]] = []
    for interaction_id, trace in traces.items():
        fb = feedback.get(interaction_id)
        if fb is None:
            if require_feedback:
                continue
            joined.append({**trace, "rating": None, "comment": ""})
            continue
        joined.append({**trace, **fb})
    return joined


def _rating_in_range(rating: Optional[int], min_rating: int, max_rating: int) -> bool:
    if rating is None:
        return False
    return min_rating <= rating <= max_rating


def _write_jsonl(path: Optional[Path], rows: Iterable[Dict[str, Any]]) -> int:
    if path is None:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as out:
        for row in rows:
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            count += 1
    return count


def _export_dpo(
    records: List[Dict[str, Any]],
    min_rating: int,
    max_rating: int,
) -> List[Dict[str, Any]]:
    buckets: Dict[str, Dict[str, List[Dict[str, Any]]]] = defaultdict(lambda: {"pos": [], "neg": []})
    for rec in records:
        rating = rec.get("rating")
        if not _rating_in_range(rating, min_rating, max_rating):
            continue
        msg = (rec.get("message") or "").strip()
        ans = (rec.get("answer") or "").strip()
        if not msg or not ans:
            continue
        if rating > 0:
            buckets[msg]["pos"].append(rec)
        elif rating < 0:
            buckets[msg]["neg"].append(rec)

    pairs: List[Dict[str, Any]] = []
    for msg, group in buckets.items():
        if not group["pos"] or not group["neg"]:
            continue
        chosen = max(group["pos"], key=lambda item: item.get("rating", 0))
        rejected = min(group["neg"], key=lambda item: item.get("rating", 0))
        pairs.append(
            {
                "prompt": msg,
                "chosen": (chosen.get("answer") or "").strip(),
                "rejected": (rejected.get("answer") or "").strip(),
                "chosen_interaction_id": chosen.get("interaction_id"),
                "rejected_interaction_id": rejected.get("interaction_id"),
            }
        )
    return pairs


def main() -> None:
    ap = argparse.ArgumentParser(description="Export tcVocLLM traces to SFT/feedback JSONL.")
    ap.add_argument("--input", default="./data/traces/agent_chat.jsonl", help="input jsonl")
    ap.add_argument("--feedback", default="./data/feedback.jsonl", help="feedback jsonl to join")
    ap.add_argument("--output", default="./data/fine_tune/sft.jsonl", help="output jsonl (all samples)")
    ap.add_argument("--positive_output", help="output jsonl for positive samples")
    ap.add_argument("--negative_output", help="output jsonl for negative samples")
    ap.add_argument("--rlhf_output", help="output jsonl for RLHF/reward modeling")
    ap.add_argument("--dpo_output", help="output jsonl for DPO preferences")
    ap.add_argument("--include_system", action="store_true", help="prepend a system message for each sample")
    ap.add_argument("--min_rating", type=int, default=-1, help="minimum rating to keep (-1~1)")
    ap.add_argument("--max_rating", type=int, default=1, help="maximum rating to keep (-1~1)")
    ap.add_argument("--require_feedback", action="store_true", help="drop traces without feedback")
    args = ap.parse_args()

    in_path = Path(args.input)
    feedback_path = Path(args.feedback)

    traces = _index_traces(in_path)
    feedback = _index_feedback(feedback_path) if feedback_path.exists() else {}
    records = _join_traces_feedback(traces, feedback, args.require_feedback)

    filtered = []
    for rec in records:
        rating = rec.get("rating")
        if rating is None and args.require_feedback:
            continue
        if rating is not None and not _rating_in_range(rating, args.min_rating, args.max_rating):
            continue
        filtered.append(rec)

    sft_rows = []
    positive_rows = []
    negative_rows = []
    rlhf_rows = []
    for rec in filtered:
        msg = (rec.get("message") or "").strip()
        ans = (rec.get("answer") or "").strip()
        if not msg or not ans:
            continue
        rating = rec.get("rating")

        sft_rows.append(_build_sft_sample(msg, ans, args.include_system))
        if rating is not None:
            rlhf_rows.append(
                {
                    "prompt": msg,
                    "response": ans,
                    "score": rating,
                    "interaction_id": rec.get("interaction_id"),
                    "comment": rec.get("comment", ""),
                }
            )
            if rating > 0:
                positive_rows.append(_build_sft_sample(msg, ans, args.include_system))
            elif rating < 0:
                negative_rows.append(_build_sft_sample(msg, ans, args.include_system))

    output_path = Path(args.output) if args.output else None
    positive_path = Path(args.positive_output) if args.positive_output else None
    negative_path = Path(args.negative_output) if args.negative_output else None
    rlhf_path = Path(args.rlhf_output) if args.rlhf_output else None
    dpo_path = Path(args.dpo_output) if args.dpo_output else None

    counts = {
        "sft": _write_jsonl(output_path, sft_rows),
        "positive": _write_jsonl(positive_path, positive_rows),
        "negative": _write_jsonl(negative_path, negative_rows),
        "rlhf": _write_jsonl(rlhf_path, rlhf_rows),
        "dpo": _write_jsonl(dpo_path, _export_dpo(filtered, args.min_rating, args.max_rating)),
    }

    for key, count in counts.items():
        if count:
            print(f"wrote {count} {key} samples")


if __name__ == "__main__":
    main()
