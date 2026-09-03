from __future__ import annotations

import json
from collections.abc import Callable
from uuid import UUID

from fastapi.testclient import TestClient

from grounded_tutor.adapters.fakes import FakeFastGPT
from grounded_tutor.adapters.fastgpt import DatasetRef
from grounded_tutor.domain.models import Source, SourceStatus, Workspace


def _register_dataset(fake: FakeFastGPT, workspace: Workspace) -> None:
    fake.datasets[workspace.dataset_id] = DatasetRef(workspace.dataset_id)


def _ingest_text(
    client: TestClient,
    workspace: Workspace,
    fake: FakeFastGPT,
    *,
    name: str = "notes",
    text: str = "Mean is an average.",
) -> dict[str, object]:
    _register_dataset(fake, workspace)
    response = client.post(
        f"/api/workspaces/{workspace.id}/sources/text",
        json={"source_name": name, "text": text, "settings": {}},
    )
    assert response.status_code == 201
    return response.json()


def _accept(client: TestClient, workspace: Workspace, source_id: str) -> dict[str, object]:
    response = client.post(f"/api/workspaces/{workspace.id}/sources/{source_id}/accept")
    assert response.status_code == 200
    return response.json()


def test_accept_requires_actual_processed_items(
    client: TestClient,
    seeded_workspace: Workspace,
    fake_fastgpt: FakeFastGPT,
    api_session_factory: Callable[[], object],
) -> None:
    created = _ingest_text(client, seeded_workspace, fake_fastgpt)
    source_id = created["source"]["id"]
    fake_fastgpt.collections["collection-1"].chunks = []

    response = client.post(f"/api/workspaces/{seeded_workspace.id}/sources/{source_id}/accept")

    assert response.status_code == 409
    assert response.json() == {"detail": {"code": "empty_processed_source"}}
    assert fake_fastgpt.collections["collection-1"].forbidden is True
    with api_session_factory() as session:
        stored = session.get(Source, UUID(source_id))
    assert stored is not None
    assert stored.status is SourceStatus.REVIEW


def test_ready_text_source_reprocesses_as_a_disabled_new_lineage_version(
    client: TestClient,
    seeded_workspace: Workspace,
    fake_fastgpt: FakeFastGPT,
    api_session_factory: Callable[[], object],
) -> None:
    original_source = _ingest_text(client, seeded_workspace, fake_fastgpt)["source"]
    _accept(client, seeded_workspace, original_source["id"])

    response = client.post(
        f"/api/workspaces/{seeded_workspace.id}/sources/{original_source['id']}/reprocess/text",
        json={
            "source_name": "revised notes",
            "text": "Median is the middle value.",
            "settings": {"chunkSize": 1200},
        },
    )

    assert response.status_code == 201
    revised = response.json()["source"]
    assert revised["status"] == "review"
    assert revised["version"] == original_source["version"] + 1
    assert revised["replaces_source_id"] == original_source["id"]
    assert revised["lineage_id"] == original_source["lineage_id"]
    assert revised["superseded_at"] is None
    assert revised["deleted_at"] is None
    assert fake_fastgpt.create_text_collection_calls[-1][2] == "Median is the middle value."
    assert fake_fastgpt.collections["collection-1"].forbidden is False
    assert fake_fastgpt.collections["collection-2"].forbidden is True
    with api_session_factory() as session:
        old = session.get(Source, UUID(original_source["id"]))
        new = session.get(Source, UUID(revised["id"]))
    assert old is not None and old.superseded_at is None
    assert new is not None and new.lineage_id == old.lineage_id


def test_file_reprocess_requires_and_forwards_new_original_bytes(
    client: TestClient,
    seeded_workspace: Workspace,
    fake_fastgpt: FakeFastGPT,
) -> None:
    _register_dataset(fake_fastgpt, seeded_workspace)
    created = client.post(
        f"/api/workspaces/{seeded_workspace.id}/sources/file",
        files={"file": ("week-1.pdf", b"old bytes", "application/pdf")},
        data={"settings": "{}"},
    )
    assert created.status_code == 201
    old = created.json()["source"]
    _accept(client, seeded_workspace, old["id"])

    missing = client.post(
        f"/api/workspaces/{seeded_workspace.id}/sources/{old['id']}/reprocess/file",
        data={"settings": "{}"},
    )
    response = client.post(
        f"/api/workspaces/{seeded_workspace.id}/sources/{old['id']}/reprocess/file",
        files={"file": ("week-2.pdf", b"new bytes", "application/pdf")},
        data={"settings": json.dumps({"chunkSize": 1200})},
    )

    assert missing.status_code == 422
    assert missing.json() == {"detail": {"code": "validation_error"}}
    assert response.status_code == 201
    revised = response.json()["source"]
    assert revised["source_type"] == "file"
    assert revised["replaces_source_id"] == old["id"]
    assert fake_fastgpt.create_file_collection_calls[-1][2] == b"new bytes"


def test_text_reprocess_requires_nonempty_new_original_text(
    client: TestClient,
    seeded_workspace: Workspace,
    fake_fastgpt: FakeFastGPT,
) -> None:
    original = _ingest_text(client, seeded_workspace, fake_fastgpt)
    source_id = original["source"]["id"]
    _accept(client, seeded_workspace, source_id)

    missing = client.post(
        f"/api/workspaces/{seeded_workspace.id}/sources/{source_id}/reprocess/text",
        json={"source_name": "notes", "settings": {}},
    )
    empty = client.post(
        f"/api/workspaces/{seeded_workspace.id}/sources/{source_id}/reprocess/text",
        json={"source_name": "notes", "text": "   ", "settings": {}},
    )

    assert missing.status_code == 422
    assert missing.json() == {"detail": {"code": "validation_error"}}
    assert empty.status_code == 422
    assert empty.json() == {"detail": {"code": "empty_source"}}


def test_accepting_reprocessed_source_supersedes_old_version_and_filters_it(
    client: TestClient,
    seeded_workspace: Workspace,
    fake_fastgpt: FakeFastGPT,
    api_session_factory: Callable[[], object],
) -> None:
    original = _ingest_text(client, seeded_workspace, fake_fastgpt)["source"]
    _accept(client, seeded_workspace, original["id"])
    revised = client.post(
        f"/api/workspaces/{seeded_workspace.id}/sources/{original['id']}/reprocess/text",
        json={"source_name": "notes v2", "text": "Revised.", "settings": {}},
    ).json()["source"]

    accepted = _accept(client, seeded_workspace, revised["id"])
    listed = client.get(f"/api/workspaces/{seeded_workspace.id}/sources")
    workspace = client.get(f"/api/workspaces/{seeded_workspace.id}")

    assert accepted["status"] == "ready"
    assert fake_fastgpt.collections["collection-1"].forbidden is True
    assert fake_fastgpt.collections["collection-2"].forbidden is False
    assert [item["id"] for item in listed.json()] == [revised["id"]]
    assert workspace.json()["source_count"] == 1
    assert workspace.json()["ready_source_count"] == 1
    with api_session_factory() as session:
        old = session.get(Source, UUID(original["id"]))
    assert old is not None and old.superseded_at is not None


def test_old_collection_disable_failure_re_forbids_new_and_keeps_local_state(
    client: TestClient,
    seeded_workspace: Workspace,
    fake_fastgpt: FakeFastGPT,
    api_session_factory: Callable[[], object],
) -> None:
    original = _ingest_text(client, seeded_workspace, fake_fastgpt)["source"]
    _accept(client, seeded_workspace, original["id"])
    revised = client.post(
        f"/api/workspaces/{seeded_workspace.id}/sources/{original['id']}/reprocess/text",
        json={"source_name": "notes v2", "text": "Revised.", "settings": {}},
    ).json()["source"]
    original_set_forbidden = fake_fastgpt.set_collection_forbidden

    async def fail_old_disable(collection_id: str, forbidden: bool) -> None:
        if collection_id == "collection-1" and forbidden:
            raise RuntimeError("private remote failure")
        await original_set_forbidden(collection_id, forbidden)

    fake_fastgpt.set_collection_forbidden = fail_old_disable
    response = client.post(f"/api/workspaces/{seeded_workspace.id}/sources/{revised['id']}/accept")

    assert response.status_code == 502
    assert response.json() == {"detail": {"code": "external_service_error"}}
    assert fake_fastgpt.collections["collection-1"].forbidden is False
    assert fake_fastgpt.collections["collection-2"].forbidden is True
    with api_session_factory() as session:
        old = session.get(Source, UUID(original["id"]))
        new = session.get(Source, UUID(revised["id"]))
    assert old is not None and old.status is SourceStatus.READY and old.superseded_at is None
    assert new is not None and new.status is SourceStatus.REVIEW


def test_invalid_lifecycle_status_and_cross_workspace_are_rejected(
    client: TestClient,
    seeded_workspace: Workspace,
    fake_fastgpt: FakeFastGPT,
    api_session_factory: Callable[[], object],
) -> None:
    created = _ingest_text(client, seeded_workspace, fake_fastgpt)["source"]
    with api_session_factory() as session:
        other = Workspace(title="Other", dataset_id="dataset-other")
        session.add(other)
        session.commit()
        session.refresh(other)

    reprocess_review = client.post(
        f"/api/workspaces/{seeded_workspace.id}/sources/{created['id']}/reprocess/text",
        json={"source_name": "notes", "text": "Again.", "settings": {}},
    )
    cross_accept = client.post(f"/api/workspaces/{other.id}/sources/{created['id']}/accept")
    _accept(client, seeded_workspace, created["id"])
    accept_ready = client.post(
        f"/api/workspaces/{seeded_workspace.id}/sources/{created['id']}/accept"
    )

    assert reprocess_review.status_code == 409
    assert reprocess_review.json() == {"detail": {"code": "invalid_source_transition"}}
    assert cross_accept.status_code == 404
    assert cross_accept.json() == {"detail": {"code": "source_not_found"}}
    assert accept_ready.status_code == 409
    assert accept_ready.json() == {"detail": {"code": "invalid_source_transition"}}


def test_delete_soft_deletes_source_filters_counts_and_disables_collection(
    client: TestClient,
    seeded_workspace: Workspace,
    fake_fastgpt: FakeFastGPT,
    api_session_factory: Callable[[], object],
) -> None:
    created = _ingest_text(client, seeded_workspace, fake_fastgpt)["source"]
    _accept(client, seeded_workspace, created["id"])

    response = client.delete(f"/api/workspaces/{seeded_workspace.id}/sources/{created['id']}")
    listed = client.get(f"/api/workspaces/{seeded_workspace.id}/sources")
    workspace = client.get(f"/api/workspaces/{seeded_workspace.id}")

    assert response.status_code == 204
    assert response.content == b""
    assert fake_fastgpt.collections["collection-1"].forbidden is True
    assert listed.json() == []
    assert workspace.json()["source_count"] == 0
    assert workspace.json()["ready_source_count"] == 0
    with api_session_factory() as session:
        stored = session.get(Source, UUID(created["id"]))
    assert stored is not None and stored.deleted_at is not None


def test_delete_remote_failure_keeps_source_visible(
    client: TestClient,
    seeded_workspace: Workspace,
    fake_fastgpt: FakeFastGPT,
    api_session_factory: Callable[[], object],
) -> None:
    created = _ingest_text(client, seeded_workspace, fake_fastgpt)["source"]
    _accept(client, seeded_workspace, created["id"])

    async def fail_disable(collection_id: str, forbidden: bool) -> None:
        del collection_id, forbidden
        raise RuntimeError("private failure")

    fake_fastgpt.set_collection_forbidden = fail_disable

    response = client.delete(f"/api/workspaces/{seeded_workspace.id}/sources/{created['id']}")
    listed = client.get(f"/api/workspaces/{seeded_workspace.id}/sources")

    assert response.status_code == 502
    assert response.json() == {"detail": {"code": "external_service_error"}}
    assert [source["id"] for source in listed.json()] == [created["id"]]
    with api_session_factory() as session:
        stored = session.get(Source, UUID(created["id"]))
    assert stored is not None and stored.deleted_at is None


def test_reprocess_rejects_second_pending_replacement(
    client: TestClient,
    seeded_workspace: Workspace,
    fake_fastgpt: FakeFastGPT,
) -> None:
    original = _ingest_text(client, seeded_workspace, fake_fastgpt)["source"]
    _accept(client, seeded_workspace, original["id"])
    first = client.post(
        f"/api/workspaces/{seeded_workspace.id}/sources/{original['id']}/reprocess/text",
        json={"source_name": "notes v2", "text": "Replacement.", "settings": {}},
    )

    second = client.post(
        f"/api/workspaces/{seeded_workspace.id}/sources/{original['id']}/reprocess/text",
        json={"source_name": "notes v3", "text": "Another.", "settings": {}},
    )

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json() == {"detail": {"code": "invalid_source_transition"}}
    assert len(fake_fastgpt.collections) == 2


def test_delete_rejects_ready_source_with_pending_replacement(
    client: TestClient,
    seeded_workspace: Workspace,
    fake_fastgpt: FakeFastGPT,
) -> None:
    original = _ingest_text(client, seeded_workspace, fake_fastgpt)["source"]
    _accept(client, seeded_workspace, original["id"])
    replacement = client.post(
        f"/api/workspaces/{seeded_workspace.id}/sources/{original['id']}/reprocess/text",
        json={"source_name": "notes v2", "text": "Replacement.", "settings": {}},
    )
    assert replacement.status_code == 201

    response = client.delete(
        f"/api/workspaces/{seeded_workspace.id}/sources/{original['id']}"
    )

    assert response.status_code == 409
    assert response.json() == {"detail": {"code": "invalid_source_transition"}}
    assert fake_fastgpt.collections["collection-1"].forbidden is False


def test_failed_replacement_does_not_block_reprocess_retry(
    client: TestClient,
    seeded_workspace: Workspace,
    fake_fastgpt: FakeFastGPT,
) -> None:
    original = _ingest_text(client, seeded_workspace, fake_fastgpt)["source"]
    _accept(client, seeded_workspace, original["id"])
    fake_fastgpt.failures["create_text_collection"] = RuntimeError("private failure")

    failed = client.post(
        f"/api/workspaces/{seeded_workspace.id}/sources/{original['id']}/reprocess/text",
        json={"source_name": "notes v2", "text": "Replacement.", "settings": {}},
    )
    retry = client.post(
        f"/api/workspaces/{seeded_workspace.id}/sources/{original['id']}/reprocess/text",
        json={"source_name": "notes v3", "text": "Retry.", "settings": {}},
    )

    assert failed.status_code == 502
    assert retry.status_code == 201
    assert retry.json()["source"]["status"] == "review"
