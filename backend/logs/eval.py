import argparse
import json
from typing import Any, Dict, Iterable, List, Tuple

from backend.logs.troubleshoot import recommend_troubleshooting


def _load_queries(path: str) -> List[Dict[str, Any]]:
    queries: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as handle:
        for idx, line in enumerate(handle, 1):
            raw = line.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON on line {idx}: {exc}") from exc
            if "log_text" not in obj:
                raise ValueError(f"Missing log_text on line {idx}")
            queries.append(obj)
    return queries


def _normalize(text: str) -> str:
    return (text or "").strip().lower()


def _match_expected(item: Dict[str, Any], expected: Iterable[str]) -> bool:
    section_path = _normalize(item.get("section_path", ""))
    section_title = _normalize(item.get("section_title", ""))
    snippet = _normalize(item.get("snippet", ""))
    haystack = "\n".join([section_path, section_title, snippet])
    for candidate in expected:
        cand = _normalize(candidate)
        if cand and cand in haystack:
            return True
    return False


def _evaluate_one(log_text: str, expected: List[str]) -> Tuple[bool, bool, bool]:
    result = recommend_troubleshooting(log_text=log_text)
    matches = result.get("matches", [])
    used_reranker = bool(result.get("used_reranker"))

    top1_hit = False
    top3_hit = False

    if matches:
        top1_hit = _match_expected(matches[0], expected)
        top3_hit = any(_match_expected(item, expected) for item in matches[:3])

    return top1_hit, top3_hit, used_reranker


def run(path: str) -> Dict[str, Any]:
    queries = _load_queries(path)
    total = len(queries)
    if total == 0:
        raise ValueError("No queries found in the evaluation file.")

    top1 = 0
    top3 = 0
    reranker_used = 0

    for query in queries:
        log_text = query.get("log_text", "")
        expected = query.get("expected", []) or []
        if not isinstance(expected, list):
            raise ValueError("expected must be a list of strings.")

        top1_hit, top3_hit, used_reranker = _evaluate_one(log_text, expected)

        top1 += int(top1_hit)
        top3 += int(top3_hit)
        reranker_used += int(used_reranker)

    return {
        "total": total,
        "top1_accuracy": top1 / total,
        "top3_accuracy": top3 / total,
        "reranker_usage": reranker_used / total,
        "top1_hits": top1,
        "top3_hits": top3,
        "reranker_used": reranker_used,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate troubleshooting recommendations.")
    parser.add_argument(
        "--input",
        required=True,
        help="Path to log evaluation JSONL file.",
    )
    args = parser.parse_args()

    metrics = run(args.input)
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
