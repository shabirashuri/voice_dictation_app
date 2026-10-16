"""Measure extraction quality on hand-written dictations (Step 5).

Runs the real chunk and finish graphs with the configured LLM (no AssemblyAI,
no database) and scores each case against its expectations. Compares the run
with baseline.json and exits 1 on regression.

    python evals/run_eval.py                     # run and compare with baseline
    python evals/run_eval.py --update-baseline   # accept this run as the baseline

LLM output varies between runs. Thresholds allow small swings; repeat a run
before deciding a change is a regression.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import statistics
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))  # backend/

from dotenv import load_dotenv  # noqa: E402

load_dotenv(HERE.parent / ".env")

from app.graph.grounding import check_grounding  # noqa: E402
from app.graph.routers import finalize, process_chunk  # noqa: E402
from app.services.llm.provider import LLMRateLimitError, build_default_llm  # noqa: E402
from app.services.streaming.manager import session_manager  # noqa: E402

FIELDS = ("patient", "specimen", "gross_description", "microscopic_description", "diagnosis", "comments")
# Free-tier providers rate-limit long runs. A rate-limited call leaves state
# unchanged, so it is retried after a pause; only the successful attempt is timed.
RATE_LIMIT_ATTEMPTS = 12
RATE_LIMIT_WAIT_S = 20.0
RECALL_DROP_TOLERANCE = 0.05   # absolute drop in field recall that counts as a regression
MISROUTE_RISE_TOLERANCE = 0.05
REJECTED_RISE_TOLERANCE = 1    # rejected chunks
INVENTED_RISE_TOLERANCE = 1    # grounding problems


def norm(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s.%°µ-]", " ", text.lower()).split())


def contains(text: str, phrase: str) -> bool:
    """True if any alternative in `phrase` ("a|b") appears in text, as whole words.

    Whole-word matching stops "5 cm" from matching inside "2.5 cm".
    """
    haystack = norm(text)
    for alternative in phrase.split("|"):
        needle = norm(alternative)
        if needle and re.search(rf"(?<![\w.]){re.escape(needle)}(?![\w])", haystack):
            return True
    return False


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, round((pct / 100) * (len(ordered) - 1)))
    return ordered[index]


async def _timed(call):
    """Run `call`, retrying rate limits; return (result, seconds of the successful attempt)."""
    for attempt in range(1, RATE_LIMIT_ATTEMPTS + 1):
        started = time.perf_counter()
        try:
            result = await call()
            return result, time.perf_counter() - started
        except LLMRateLimitError:
            if attempt == RATE_LIMIT_ATTEMPTS:
                raise
            print(f"  rate limited; waiting {RATE_LIMIT_WAIT_S:.0f}s (attempt {attempt})", flush=True)
            await asyncio.sleep(RATE_LIMIT_WAIT_S)


async def run_case(case: dict, llm) -> dict:
    sid = f"eval-{case['id']}-{uuid.uuid4().hex[:8]}"
    chunk_latencies: list[float] = []
    rejected = 0
    try:
        for chunk in case["chunks"]:
            result, seconds = await _timed(lambda c=chunk: process_chunk(sid, c, llm=llm))
            chunk_latencies.append(seconds)
            if result.get("error_code"):
                rejected += 1
        # A rate-limited AI comment comes back as an error code, not an exception.
        for attempt in range(1, RATE_LIMIT_ATTEMPTS + 1):
            final, finalize_latency = await _timed(lambda: finalize(sid, llm=llm))
            if final.get("error_code") != "llm_rate_limit" or attempt == RATE_LIMIT_ATTEMPTS:
                break
            print(f"  AI comment rate limited; waiting {RATE_LIMIT_WAIT_S:.0f}s", flush=True)
            await asyncio.sleep(RATE_LIMIT_WAIT_S)
    finally:
        session_manager.discard(sid)

    report = final["report"]
    dictation = " ".join(case["chunks"])
    comment_source = report.get("comment_source")

    expected = [(field, phrase) for field, phrases in case.get("expect", {}).items() for phrase in phrases]
    found_correct = misrouted = missed = 0
    for field, phrase in expected:
        if contains(report.get(field, ""), phrase):
            found_correct += 1
        elif any(contains(report.get(other, ""), phrase) for other in FIELDS if other != field):
            misrouted += 1
        else:
            missed += 1

    forbidden_hits = [p for p in case.get("forbid", []) if any(contains(report.get(f, ""), p) for f in FIELDS)]

    # Grounding: fields the model wrote must be supported by the dictation.
    # AI-written comments are judged by the comment guard instead, not here.
    invented = 0
    for field in FIELDS:
        if field == "comments" and comment_source == "ai":
            continue
        value = report.get(field, "")
        if value:
            invented += len(check_grounding(dictation, value, label=field))

    empty_ok = True
    if case.get("expect_empty"):
        empty_ok = not any(report.get(f) for f in FIELDS)
    source_ok = True
    if "expect_comment_source" in case:
        source_ok = comment_source in case["expect_comment_source"]

    passed = (
        found_correct == len(expected)
        and not forbidden_hits
        and invented == 0
        and rejected == 0
        and empty_ok
        and source_ok
    )
    return {
        "id": case["id"],
        "passed": passed,
        "expected": len(expected),
        "found_correct": found_correct,
        "misrouted": misrouted,
        "missed": missed,
        "forbidden_hits": forbidden_hits,
        "invented": invented,
        "rejected_chunks": rejected,
        "comment_source": comment_source,
        "chunks": len(case["chunks"]),
        "chunk_latency_s": [round(x, 3) for x in chunk_latencies],
        "finalize_latency_s": round(finalize_latency, 3),
        "report": {f: report.get(f, "") for f in FIELDS},
    }


def summarise(results: list[dict]) -> dict:
    expected = sum(r["expected"] for r in results)
    latencies = [x for r in results for x in r["chunk_latency_s"]]
    return {
        "cases": len(results),
        "cases_passed": sum(r["passed"] for r in results),
        "field_recall": round(sum(r["found_correct"] for r in results) / expected, 3) if expected else 1.0,
        "misroute_rate": round(sum(r["misrouted"] for r in results) / expected, 3) if expected else 0.0,
        "forbidden_hits": sum(len(r["forbidden_hits"]) for r in results),
        "invented_problems": sum(r["invented"] for r in results),
        "rejected_chunks": sum(r["rejected_chunks"] for r in results),
        "chunk_latency_p50_s": round(percentile(latencies, 50), 3),
        "chunk_latency_p95_s": round(percentile(latencies, 95), 3),
        "finalize_latency_p50_s": round(percentile([r["finalize_latency_s"] for r in results], 50), 3),
    }


def compare(current: dict, baseline: dict) -> list[str]:
    problems = []
    if current["field_recall"] < baseline["field_recall"] - RECALL_DROP_TOLERANCE:
        problems.append(f"field recall fell {baseline['field_recall']} -> {current['field_recall']}")
    if current["misroute_rate"] > baseline["misroute_rate"] + MISROUTE_RISE_TOLERANCE:
        problems.append(f"misroute rate rose {baseline['misroute_rate']} -> {current['misroute_rate']}")
    if current["forbidden_hits"] > baseline["forbidden_hits"]:
        problems.append(f"forbidden content rose {baseline['forbidden_hits']} -> {current['forbidden_hits']}")
    if current["invented_problems"] > baseline["invented_problems"] + INVENTED_RISE_TOLERANCE:
        problems.append(f"invented content rose {baseline['invented_problems']} -> {current['invented_problems']}")
    if current["rejected_chunks"] > baseline["rejected_chunks"] + REJECTED_RISE_TOLERANCE:
        problems.append(f"rejected chunks rose {baseline['rejected_chunks']} -> {current['rejected_chunks']}")
    return problems


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", default=str(HERE / "cases.json"))
    parser.add_argument("--update-baseline", action="store_true")
    args = parser.parse_args()

    if not os.getenv("GROQ_API_KEY"):
        print("GROQ_API_KEY is not set; the eval needs the real LLM.", file=sys.stderr)
        return 2

    cases = json.loads(Path(args.cases).read_text(encoding="utf-8"))
    llm = build_default_llm()
    results = []
    for case in cases:
        result = await run_case(case, llm)
        results.append(result)
        status = "PASS" if result["passed"] else "FAIL"
        print(f"{status}  {case['id']:<28} recall {result['found_correct']}/{result['expected']}"
              f"  misrouted {result['misrouted']}  forbidden {len(result['forbidden_hits'])}"
              f"  invented {result['invented']}  rejected {result['rejected_chunks']}", flush=True)

    summary = summarise(results)
    run = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "llm_model": getattr(llm, "model", type(llm).__name__),
        "summary": summary,
        "cases": results,
    }
    out_dir = HERE / "results"
    out_dir.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (out_dir / f"run-{stamp}.json").write_text(json.dumps(run, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "latest.json").write_text(json.dumps(run, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\nSUMMARY", json.dumps(summary, indent=2))

    baseline_path = HERE / "baseline.json"
    if args.update_baseline:
        baseline_path.write_text(json.dumps(run, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"baseline written: {baseline_path}")
        return 0
    if not baseline_path.exists():
        print("no baseline.json yet; run with --update-baseline to create one")
        return 0
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))["summary"]
    problems = compare(summary, baseline)
    if problems:
        print("\nREGRESSION:\n  - " + "\n  - ".join(problems))
        return 1
    print("\nno regression against baseline")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
