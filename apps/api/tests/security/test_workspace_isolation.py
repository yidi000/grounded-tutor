"""Exercise workspace boundaries through real routes and migrated SQLite storage."""

from uuid import UUID, uuid4

import pytest
from api import conftest as api_fixtures
from sqlalchemy import func, select

from grounded_tutor.adapters.fastgpt import RetrievedChunk
from grounded_tutor.domain.models import Conversation, Message, RequestRecord, Source

# Reuse the migrated API client without widening fixture scope for unrelated suites.
api_engine = api_fixtures.api_engine
api_session_factory = api_fixtures.api_session_factory
client = api_fixtures.client
fake_fastgpt = api_fixtures.fake_fastgpt
fake_generation = api_fixtures.fake_generation


@pytest.fixture
def workspaces(client):
    result = []
    for name in ("Alpha", "Beta"):
        response = client.post("/api/workspaces", json={"title": name})
        assert response.status_code == 201
        workspace_id = response.json()["id"]
        source = client.post(
            f"/api/workspaces/{workspace_id}/sources/text",
            json={"source_name": f"{name} notes", "text": f"{name} private evidence."},
        )
        assert source.status_code == 201
        result.append((workspace_id, source.json()["source"]["id"]))
    return result


@pytest.mark.parametrize(
    "operation", ["preview", "accept", "reprocess_text", "reprocess_file", "delete"]
)
def test_source_operations_hide_other_workspace_ids_without_side_effects(
    client, workspaces, api_session_factory, fake_fastgpt, operation
):
    (workspace_a, source_a), (workspace_b, _) = workspaces
    if operation.startswith("reprocess"):
        assert (
            client.post(f"/api/workspaces/{workspace_a}/sources/{source_a}/accept").status_code
            == 200
        )
    original = client.get(f"/api/workspaces/{workspace_a}/sources").json()
    calls = list(fake_fastgpt.call_history)

    def request(source_id):
        url = f"/api/workspaces/{workspace_b}/sources/{source_id}"
        if operation == "preview":
            return client.get(url + "/processed-preview")
        if operation == "accept":
            return client.post(url + "/accept")
        if operation == "reprocess_text":
            return client.post(
                url + "/reprocess/text", json={"source_name": "Replacement", "text": "New text"}
            )
        if operation == "reprocess_file":
            return client.post(
                url + "/reprocess/file",
                files={"file": ("replacement.txt", b"New text", "text/plain")},
            )
        return client.delete(url)

    foreign, missing = request(source_a), request(uuid4())
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json() == {"detail": {"code": "source_not_found"}}
    assert fake_fastgpt.call_history == calls
    assert client.get(f"/api/workspaces/{workspace_a}/sources").json() == original
    assert source_a not in client.get(f"/api/workspaces/{workspace_b}/sources").text
    with api_session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Source)) == 2


def test_chat_cannot_append_to_another_workspace_conversation(
    client, workspaces, api_session_factory, fake_fastgpt, fake_generation
):
    (workspace_a, _), (workspace_b, _) = workspaces
    original = client.post(
        f"/api/workspaces/{workspace_a}/chat",
        json={"message": "Alpha question", "idempotency_key": "original"},
    )
    assert original.status_code == 200
    calls = list(fake_fastgpt.call_history), list(fake_generation.calls)
    for conversation_id in (original.json()["conversation_id"], str(uuid4())):
        denied = client.post(
            f"/api/workspaces/{workspace_b}/chat",
            json={
                "message": "Beta question",
                "idempotency_key": "denied",
                "conversation_id": conversation_id,
            },
        )
        assert denied.status_code == 404
        assert denied.json() == {"detail": {"code": "workspace_not_found"}}
    assert (fake_fastgpt.call_history, fake_generation.calls) == calls
    assert client.get(f"/api/workspaces/{workspace_b}/chat/history").json() == {"exchanges": []}
    with api_session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Conversation)) == 1
        assert session.scalar(select(func.count()).select_from(Message)) == 2
        assert (
            session.scalar(
                select(func.count())
                .select_from(RequestRecord)
                .where(RequestRecord.workspace_id == UUID(workspace_b))
            )
            == 0
        )


def test_history_replay_and_citations_remain_in_their_workspace(
    client, workspaces, fake_fastgpt, fake_generation
):
    answers = []
    payload = {"message": "Summarize the evidence", "idempotency_key": "same-key"}
    for workspace_id, source_id in workspaces:
        assert (
            client.post(f"/api/workspaces/{workspace_id}/sources/{source_id}/accept").status_code
            == 200
        )
        response = client.post(f"/api/workspaces/{workspace_id}/chat", json=payload)
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
        assert {item["source_id"] for item in response.json()["citations"]} == {source_id}
        answers.append(response.json())
    assert answers[0]["conversation_id"] != answers[1]["conversation_id"]
    assert answers[0]["message_id"] != answers[1]["message_id"]
    calls = list(fake_fastgpt.call_history), list(fake_generation.calls)
    for index, (workspace_id, _) in enumerate(workspaces):
        url = f"/api/workspaces/{workspace_id}/chat"
        assert client.post(url, json=payload).json() == answers[index]
        history = client.get(url + "/history")
        assert history.status_code == 200
        assert history.json() == {
            "exchanges": [
                {
                    "question": payload["message"],
                    "response": answers[index],
                    "legacy_content": None,
                }
            ]
        }
        assert workspaces[1 - index][1] not in history.text
        assert answers[1 - index]["message_id"] not in history.text
    assert (fake_fastgpt.call_history, fake_generation.calls) == calls


@pytest.mark.parametrize("include_local", [False, True])
def test_foreign_retrieval_chunks_never_reach_generation_or_citations(
    client, workspaces, api_session_factory, fake_fastgpt, fake_generation, include_local
):
    (workspace_a, source_a), (_, source_b) = workspaces
    for workspace_id, source_id in workspaces:
        assert (
            client.post(f"/api/workspaces/{workspace_id}/sources/{source_id}/accept").status_code
            == 200
        )
    with api_session_factory() as session:
        collection_a = session.get(Source, UUID(source_a)).collection_id
        collection_b = session.get(Source, UUID(source_b)).collection_id
    foreign = RetrievedChunk(
        "same-chunk-id",
        collection_b,
        "Beta private name",
        "",
        "Beta private evidence",
        1,
    )
    local = RetrievedChunk(
        "same-chunk-id",
        collection_a,
        "untrusted provider name",
        "",
        "Alpha evidence",
        0.9,
    )
    # The foreign hit comes first and even shares a chunk ID with a permitted hit.
    fake_fastgpt.search_results_override = (foreign, local) if include_local else (foreign,)
    url = f"/api/workspaces/{workspace_a}/chat"
    payload = {"message": "Summarize", "idempotency_key": "contaminated-search"}
    response = client.post(url, json=payload)
    assert response.status_code == 200
    assert "Beta" not in response.text
    assert source_b not in response.text
    assert (
        fake_fastgpt.search_calls[-1].dataset_id
        == fake_fastgpt.collections[collection_a].dataset_id
    )
    if include_local:
        assert response.json()["status"] == "ok"
        assert len(fake_generation.calls) == 1
        assert fake_generation.calls[0].chunks == (local,)
        assert {item["source_id"] for item in response.json()["citations"]} == {source_a}
        assert {item["source_name"] for item in response.json()["citations"]} == {"Alpha notes"}
    else:
        assert response.json()["status"] == "insufficient_material"
        assert response.json()["citations"] == []
        assert fake_generation.calls == []
    assert client.post(url, json=payload).json() == response.json()
    assert "Beta" not in client.get(url + "/history").text


@pytest.mark.parametrize("hidden_field", ["deleted_at", "superseded_at"])
def test_historical_source_lookup_keeps_workspace_scope(
    workspaces, api_session_factory, hidden_field
):
    from datetime import UTC, datetime

    from grounded_tutor.repositories.sources import SourceRepository

    (workspace_a, source_a), (workspace_b, _) = workspaces
    with api_session_factory() as session:
        source = session.get(Source, UUID(source_a))
        setattr(source, hidden_field, datetime.now(UTC))
        session.commit()
        repository = SourceRepository(session)
        assert repository.get_for_workspace(UUID(workspace_a), UUID(source_a)) is None
        historical = repository.get_historical_for_workspace(UUID(workspace_a), UUID(source_a))
        assert historical.summary.id == UUID(source_a)
        assert repository.get_historical_for_workspace(UUID(workspace_b), UUID(source_a)) is None
        assert repository.get_for_workspace(UUID(workspace_b), UUID(source_a)) is None
