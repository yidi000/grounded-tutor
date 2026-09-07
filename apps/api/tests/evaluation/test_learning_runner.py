from pathlib import Path

import pytest

from grounded_tutor.evaluation.learning import load_cases, observe

CASES = load_cases(Path("evals/cases/learning.jsonl"))


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
async def test_learning_journey(case):
    assert await observe(case) == {"id": case["id"], "passed": True}
