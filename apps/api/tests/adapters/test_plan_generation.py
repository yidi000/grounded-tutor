import json

import httpx
import pytest

from grounded_tutor.adapters.fastgpt import RetrievedChunk
from grounded_tutor.adapters.generation import (
    InvalidGenerationOutput,
    OpenAICompatibleGenerationClient,
)


@pytest.mark.asyncio
async def test_plan_transport_has_separate_schema_and_only_supplied_material():
    seen = []
    data = {
        "concepts": [
            {
                "title": f"Concept {i}",
                "objective": "Explain mean",
                "chunk_ids": ["chunk"],
                "check_kind": "single_choice",
            }
            for i in range(3)
        ]
    }

    async def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(data)}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = OpenAICompatibleGenerationClient(
            "https://llm.test/v1", "secret", "model", client=http
        )
        result = await client.generate_plan(
            "Learn mean",
            {"Mean": "not_assessed"},
            (
                RetrievedChunk(
                    "chunk", "private-collection", "private-name", "Mean", "sum divided by count", 1
                ),
            ),
        )
    assert len(result.concepts) == 3
    user = json.loads(seen[0]["messages"][1]["content"])
    assert user["mode"] == "PLAN"
    assert "not_assessed" in user["instruction"]
    serialized = json.dumps(seen)
    assert "private-collection" not in serialized and "private-name" not in serialized
    system = seen[0]["messages"][0]["content"]
    assert "concepts array" in system and "untrusted" in system


@pytest.mark.asyncio
@pytest.mark.parametrize("content", ['{"blocks":[]}', '{"concepts":[]}{"concepts":[]}'])
async def test_plan_transport_rejects_other_contracts(content):
    async def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = OpenAICompatibleGenerationClient(
            "https://llm.test/v1", "secret", "model", client=http
        )
        with pytest.raises(InvalidGenerationOutput):
            await client.generate_plan("Learn", {}, ())
