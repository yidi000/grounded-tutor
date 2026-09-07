import json

import httpx
import pytest

from grounded_tutor.adapters.fastgpt import RetrievedChunk
from grounded_tutor.adapters.generation import (
    InvalidGenerationOutput,
    OpenAICompatibleGenerationClient,
)


@pytest.mark.asyncio
async def test_check_adapter_requests_one_typed_question_without_private_metadata():
    seen = []
    payload = {
        "question": {
            "id": "q",
            "kind": "single_choice",
            "prompt": "Numerator?",
            "options": ["sum", "product"],
            "answer_key": ["sum"],
            "explanation": "Use the sum.",
            "concept_label": "Mean",
            "chunk_ids": ["chunk"],
        }
    }

    async def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps(payload)}}]}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = OpenAICompatibleGenerationClient(
            "https://llm.test/v1", "secret", "model", client=http
        )
        generated = await client.generate_check(
            "Explain mean",
            "single_choice",
            (
                RetrievedChunk(
                    "chunk", "private-collection", "private-name", "Mean", "sum divided by count", 1
                ),
            ),
        )
    assert generated.question.answer_key == ("sum",)
    system = seen[0]["messages"][0]["content"]
    assert "one question" in system and "untrusted" in system
    assert "private-collection" not in json.dumps(seen) and "private-name" not in json.dumps(seen)
    assert json.loads(seen[0]["messages"][1]["content"])["mode"] == "CHECK"


@pytest.mark.asyncio
async def test_check_adapter_rejects_diagnostic_array():
    async def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"questions":[]}'}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = OpenAICompatibleGenerationClient(
            "https://llm.test/v1", "secret", "model", client=http
        )
        with pytest.raises(InvalidGenerationOutput):
            await client.generate_check("Explain mean", "single_choice", ())
