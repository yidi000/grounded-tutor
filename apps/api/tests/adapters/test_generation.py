import json

import httpx
import pytest

from grounded_tutor.adapters.fastgpt import ExternalServiceError, RetrievedChunk
from grounded_tutor.adapters.generation import (
    GenerationRequest,
    InvalidGenerationOutput,
    OpenAICompatibleGenerationClient,
)


def _request() -> GenerationRequest:
    return GenerationRequest(
        mode="ASK",
        instruction="什么是均值？",
        chunks=(
            RetrievedChunk(
                "chunk-1", "collection-private", "provider-name", "均值", "均值是平均数。", 0.9
            ),
        ),
    )


@pytest.mark.asyncio
async def test_generation_client_requests_json_and_parses_generated_blocks() -> None:
    seen: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["authorization"] = request.headers["Authorization"]
        seen["json"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "blocks": [
                                        {
                                            "id": "block-1",
                                            "kind": "answer",
                                            "text": "均值是平均数。",
                                            "chunk_ids": ["chunk-1"],
                                        }
                                    ]
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ]
            },
        )

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = OpenAICompatibleGenerationClient(
        "https://llm.test/v1/", "super-secret", "model-1", client=http
    )

    answer = await client.generate_content(_request())

    assert answer.blocks[0].text == "均值是平均数。"
    assert answer.blocks[0].chunk_ids == ("chunk-1",)
    assert seen["url"] == "https://llm.test/v1/chat/completions"
    assert seen["authorization"] == "Bearer super-secret"
    payload = seen["json"]
    assert isinstance(payload, dict)
    assert payload["model"] == "model-1"
    assert payload["response_format"] == {"type": "json_object"}
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "chunk-1" in serialized
    assert "均值是平均数。" in serialized
    assert "collection-private" not in serialized
    assert "provider-name" not in serialized
    assert "super-secret" not in serialized
    await http.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b"not-json"),
        httpx.Response(200, json={"choices": []}),
        httpx.Response(200, json={"choices": [{"message": {"content": "not-json"}}]}),
        httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"blocks":[]}{"blocks":[]}'}}]},
        ),
        httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "blocks": [
                                        {
                                            "id": "block-1",
                                            "kind": "answer",
                                            "text": "answer",
                                            "chunk_ids": ["chunk-1"],
                                            "citation_ids": ["provider-citation"],
                                        }
                                    ]
                                }
                            )
                        }
                    }
                ]
            },
        ),
    ],
)
async def test_invalid_provider_output_is_redacted_and_retryable(
    response: httpx.Response,
) -> None:
    secret_body = b'provider-private-body api-key=super-secret'

    async def handler(_request: httpx.Request) -> httpx.Response:
        if response.status_code == 200 and response.content:
            return response
        return httpx.Response(response.status_code, content=secret_body)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = OpenAICompatibleGenerationClient(
        "https://llm.test/v1", "super-secret", "model-1", client=http
    )

    with pytest.raises(InvalidGenerationOutput) as captured:
        await client.generate_content(_request())

    public = str(captured.value)
    assert "super-secret" not in public
    assert "provider-private-body" not in public
    assert captured.value.category == "invalid_output"
    assert captured.value.__context__ is None
    await http.aclose()


@pytest.mark.asyncio
async def test_network_failure_is_redacted_but_not_retryable_output_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("secret network detail", request=request)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = OpenAICompatibleGenerationClient(
        "https://llm.test/v1", "super-secret", "model-1", client=http
    )

    with pytest.raises(ExternalServiceError) as captured:
        await client.generate_content(_request())

    assert not isinstance(captured.value, InvalidGenerationOutput)
    assert "secret network detail" not in str(captured.value)
    assert captured.value.__context__ is None
    assert "super-secret" not in repr(client)
    await http.aclose()


@pytest.mark.asyncio
async def test_generation_client_closes_only_the_client_it_owns() -> None:
    owned = OpenAICompatibleGenerationClient("https://llm.test", "secret", "model")
    injected = httpx.AsyncClient()
    borrowed = OpenAICompatibleGenerationClient(
        "https://llm.test", "secret", "model", client=injected
    )

    await owned.aclose()
    await borrowed.aclose()

    assert owned.is_closed is True
    assert injected.is_closed is False
    await injected.aclose()


@pytest.mark.asyncio
async def test_diagnostic_adapter_uses_evidence_only_and_parses_questions():
    data = {'questions':[{'id':str(i),'kind':'single_choice','prompt':f'选择均值定义 {i}',
        'options':['平均数','中位数'],'answer_key':['平均数'],'explanation':'均值是平均数。',
        'concept_label':'均值','chunk_ids':['chunk-1']} for i in range(3)]}
    seen = []

    async def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={'choices':[{'message':{'content':json.dumps(data)}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        adapter = OpenAICompatibleGenerationClient('https://llm.test/v1', 'secret', 'model', client=http)
        result = await adapter.generate_diagnostic('学习均值', '初学者', _request().chunks)
    assert len(result.questions) == 3
    payload = json.dumps(seen, ensure_ascii=False)
    assert 'collection-private' not in payload and 'provider-name' not in payload
    assert 'untrusted' in payload and 'questions array' in payload
    assert '初学者' in payload and 'chunk-1' in payload


@pytest.mark.asyncio
async def test_diagnostic_adapter_rejects_ask_shape_and_concatenated_json():
    async def handler(request):
        return httpx.Response(200, json={'choices':[{'message':{'content':'{"blocks":[]}{"questions":[]}'}}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        adapter = OpenAICompatibleGenerationClient('https://llm.test/v1', 'secret', 'model', client=http)
        with pytest.raises(InvalidGenerationOutput):
            await adapter.generate_diagnostic('goal', None, _request().chunks)
