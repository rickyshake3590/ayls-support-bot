"""Manual eval: run tests/eval_questions.yaml through the full pipeline against the live LLM.

Not run in CI (the free tier is flaky). Needs OPENROUTER_API_KEY and a built index.
Usage: python -m scripts.eval_answers

Verdicts:
  PASS      negative got no answer, or positive got an answer written by the LLM
  FALLBACK  positive got an extractive answer (LLM unavailable): not a grounded pass
  FAIL      negative got an answer, or positive got no answer
"""

import asyncio
import os
import pathlib
import sys
import time

import yaml

from bot import config
from bot.rag import Answer, answer

EVAL_FILE = pathlib.Path(__file__).resolve().parent.parent / "tests" / "eval_questions.yaml"
# Free tier allows 20 requests per minute; 3.5 s between questions stays under it.
DELAY_SECONDS = float(os.getenv("EVAL_DELAY_SECONDS", "3.5"))


def verdict(case: dict, result: Answer | None) -> str:
    if case.get("expect_none"):
        return "PASS" if result is None else "FAIL"
    if result is None:
        return "FAIL"
    return "PASS" if result.mode == "llm" else "FALLBACK"


async def main() -> int:
    cases = yaml.safe_load(EVAL_FILE.read_text(encoding="utf-8"))
    print(f"model={config.LLM_MODEL} fallback={config.LLM_FALLBACK_MODEL or 'none'} "
          f"max_dist={config.MAX_DIST} top_k={config.TOP_K} "
          f"query_translate={config.QUERY_TRANSLATE} delay={DELAY_SECONDS}s")
    counts = {"PASS": 0, "FALLBACK": 0, "FAIL": 0}
    for index, case in enumerate(cases):
        if index:
            await asyncio.sleep(DELAY_SECONDS)
        start = time.monotonic()
        result = await answer(case["question"])
        latency = int((time.monotonic() - start) * 1000)
        status = verdict(case, result)
        counts[status] += 1
        print(f"[{status:8s}] {latency:6d}ms  {case['question']}")
        if result is None:
            print("             -> no answer (human offered)")
        else:
            print(f"             -> ({result.mode}) {result.text[:160]!r}")
            print(f"                source: {result.url}")
    print(f"\nPASS {counts['PASS']}  FALLBACK {counts['FALLBACK']}  FAIL {counts['FAIL']}"
          f"  of {len(cases)}")
    return 0 if counts["PASS"] == len(cases) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
