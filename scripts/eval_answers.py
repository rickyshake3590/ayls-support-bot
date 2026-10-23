"""Manual eval: run tests/eval_questions.yaml through the full pipeline against the live LLM.

Not run in CI (the free tier is flaky). Needs OPENROUTER_API_KEY and a built index.
Usage: python -m scripts.eval_answers
"""

import asyncio
import pathlib
import sys
import time

import yaml

from bot import config
from bot.rag import answer

EVAL_FILE = pathlib.Path(__file__).resolve().parent.parent / "tests" / "eval_questions.yaml"


def _passes(case: dict, result) -> bool:  # type: ignore[no-untyped-def]
    """Automatic check only: negatives must get no answer, positives must get one.

    Whether a positive answer is grounded in the right source is judged by reading the output.
    """
    if case.get("expect_none"):
        return result is None
    return result is not None


async def main() -> int:
    cases = yaml.safe_load(EVAL_FILE.read_text(encoding="utf-8"))
    print(f"model={config.LLM_MODEL} fallback={config.LLM_FALLBACK_MODEL or 'none'} "
          f"max_dist={config.MAX_DIST} query_translate={config.QUERY_TRANSLATE}")
    passed = 0
    for case in cases:
        start = time.monotonic()
        result = await answer(case["question"])
        latency = int((time.monotonic() - start) * 1000)
        ok = _passes(case, result)
        passed += ok
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {latency:6d}ms  {case['question']}")
        if result is None:
            print("           -> no answer (human offered)")
        else:
            print(f"           -> ({result.mode}) {result.text[:160]!r}")
            print(f"              source: {result.url}")
    print(f"\n{passed}/{len(cases)} passed")
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
