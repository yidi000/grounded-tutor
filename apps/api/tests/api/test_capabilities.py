import json
from collections.abc import Callable
from typing import get_args

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import func, select

from grounded_tutor.config import Settings, get_settings
from grounded_tutor.domain.models import Source
from grounded_tutor.domain.schemas import ApiErrorDetail

EXPECTED_PUBLIC_ERROR_CODES = {
    "demo_read_only",
    "empty_processed_source",
    "empty_source",
    "external_service_error",
    "file_too_large",
    "idempotency_in_progress",
    "idempotency_key_reused",
    "invalid_chunk_settings",
    "invalid_source_transition",
    "persistence_error",
    "processed_preview_unavailable",
    "request_body_too_large",
    "source_not_found",
    "source_too_large",
    "source_work_limit_exceeded",
    "text_too_large",
    "unreadable_file",
    "unsafe_archive",
    "unsupported_file_type",
    "unsupported_workspace_model",
    "validation_error",
    "workspace_ingestion_busy",
    "workspace_not_found",
}


def test_capabilities_report_only_verified_formats(client: TestClient) -> None:
    response = client.get("/api/capabilities/source-ingestion")

    assert response.status_code == 200
    assert response.json() == {
        "accepted_extensions": [
            ".csv",
            ".docx",
            ".html",
            ".md",
            ".pdf",
            ".pptx",
            ".txt",
            ".xlsx",
        ],
        "max_upload_bytes": 20_000_000,
        "settings": [
            {
                "key": "customPdfParse",
                "supported": False,
                "disabled_reason": "deployment_not_verified",
            },
            {
                "key": "imageFiles",
                "supported": False,
                "disabled_reason": "deployment_not_verified",
            },
        ],
        "workspace_models": [
            {
                "key": "vector_model",
                "supported": False,
                "disabled_reason": "deployment_not_verified",
            },
            {
                "key": "agent_model",
                "supported": False,
                "disabled_reason": "deployment_not_verified",
            },
            {
                "key": "vlm_model",
                "supported": False,
                "disabled_reason": "deployment_not_verified",
            },
        ],
        "read_only_demo": False,
    }


def test_image_capability_and_extensions_require_explicit_confirmation(
    client: TestClient,
) -> None:
    disabled = client.get("/api/capabilities/source-ingestion").json()
    assert not {".png", ".jpg", ".jpeg", ".webp"} & set(
        disabled["accepted_extensions"]
    )
    assert next(
        item for item in disabled["settings"] if item["key"] == "imageFiles"
    ) == {
        "key": "imageFiles",
        "supported": False,
        "disabled_reason": "deployment_not_verified",
    }

    client.app.dependency_overrides[get_settings] = lambda: Settings(
        supports_image_files=True
    )
    enabled = client.get("/api/capabilities/source-ingestion").json()

    assert {".png", ".jpg", ".jpeg", ".webp"} <= set(
        enabled["accepted_extensions"]
    )
    assert next(
        item for item in enabled["settings"] if item["key"] == "imageFiles"
    ) == {"key": "imageFiles", "supported": True, "disabled_reason": None}


def test_read_only_demo_still_disables_confirmed_image_ingestion(
    client: TestClient,
) -> None:
    client.app.dependency_overrides[get_settings] = lambda: Settings(
        demo_read_only=True,
        supports_image_files=True,
    )

    response = client.get("/api/capabilities/source-ingestion")

    assert response.status_code == 200
    assert next(
        item for item in response.json()["settings"] if item["key"] == "imageFiles"
    ) == {
        "key": "imageFiles",
        "supported": False,
        "disabled_reason": "demo_read_only",
    }


def test_public_error_codes_are_one_exact_validated_union(client: TestClient) -> None:
    from grounded_tutor.domain.errors import PublicErrorCode

    assert set(get_args(PublicErrorCode)) == EXPECTED_PUBLIC_ERROR_CODES
    openapi = client.get("/openapi.json").json()
    code_schema = openapi["components"]["schemas"]["ApiErrorDetail"]["properties"]["code"]
    assert set(code_schema["enum"]) == EXPECTED_PUBLIC_ERROR_CODES
    with pytest.raises(ValidationError):
        ApiErrorDetail(code="unknown")


def test_every_write_operation_documents_demo_read_only_error(
    client: TestClient,
) -> None:
    openapi = client.get("/openapi.json").json()
    writes = [
        ("post", "/api/workspaces"),
        ("patch", "/api/workspaces/{workspace_id}"),
        ("post", "/api/workspaces/{workspace_id}/source-previews/text"),
        ("post", "/api/workspaces/{workspace_id}/source-previews/file"),
        ("post", "/api/workspaces/{workspace_id}/sources/text"),
        ("post", "/api/workspaces/{workspace_id}/sources/file"),
        ("post", "/api/workspaces/{workspace_id}/sources/{source_id}/accept"),
        (
            "post",
            "/api/workspaces/{workspace_id}/sources/{source_id}/reprocess/text",
        ),
        (
            "post",
            "/api/workspaces/{workspace_id}/sources/{source_id}/reprocess/file",
        ),
        ("delete", "/api/workspaces/{workspace_id}/sources/{source_id}"),
    ]

    for method, path in writes:
        assert openapi["paths"][path][method]["responses"]["403"]["content"][
            "application/json"
        ]["schema"] == {"$ref": "#/components/schemas/ApiErrorResponse"}


def test_source_ingestion_writes_document_body_and_service_limits(
    client: TestClient,
) -> None:
    openapi = client.get("/openapi.json").json()
    paths = [
        "/api/workspaces/{workspace_id}/sources/text",
        "/api/workspaces/{workspace_id}/sources/file",
        "/api/workspaces/{workspace_id}/sources/{source_id}/reprocess/text",
        "/api/workspaces/{workspace_id}/sources/{source_id}/reprocess/file",
    ]

    for path in paths:
        assert openapi["paths"][path]["post"]["responses"]["413"]["content"][
            "application/json"
        ]["schema"] == {"$ref": "#/components/schemas/ApiErrorResponse"}


def test_disabled_custom_pdf_parse_is_rejected_before_preview_service(
    client: TestClient,
    seeded_workspace,
    api_session_factory: Callable[[], object],
    fake_fastgpt,
) -> None:
    response = client.post(
        f"/api/workspaces/{seeded_workspace.id}/source-previews/text",
        json={
            "source_name": "notes.txt",
            "text": "hello",
            "settings": {"customPdfParse": True},
        },
    )

    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "invalid_chunk_settings"}}
    assert fake_fastgpt.call_history == []
    assert _source_count(api_session_factory) == 0


@pytest.mark.parametrize(
    "path",
    [
        "/api/workspaces/{workspace_id}/sources/text",
        (
            "/api/workspaces/{workspace_id}/sources/"
            "00000000-0000-0000-0000-000000000000/reprocess/text"
        ),
    ],
)
def test_disabled_custom_pdf_parse_is_rejected_for_ingestion_and_reprocess(
    client: TestClient,
    seeded_workspace,
    fake_fastgpt,
    api_session_factory: Callable[[], object],
    path: str,
) -> None:
    response = client.post(
        path.format(workspace_id=seeded_workspace.id),
        json={
            "source_name": "notes.txt",
            "text": "hello",
            "settings": {"customPdfParse": True},
        },
    )

    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "invalid_chunk_settings"}}
    assert fake_fastgpt.call_history == []
    assert _source_count(api_session_factory) == 0


@pytest.mark.parametrize(
    "path",
    [
        "/api/workspaces/{workspace_id}/source-previews/file",
        "/api/workspaces/{workspace_id}/sources/file",
        (
            "/api/workspaces/{workspace_id}/sources/"
            "00000000-0000-0000-0000-000000000000/reprocess/file"
        ),
    ],
)
def test_disabled_custom_pdf_parse_is_rejected_for_file_operations_without_writes(
    client: TestClient,
    seeded_workspace,
    fake_fastgpt,
    api_session_factory: Callable[[], object],
    path: str,
) -> None:
    response = client.post(
        path.format(workspace_id=seeded_workspace.id),
        files={"file": ("notes.txt", b"hello", "text/plain")},
        data={"settings": json.dumps({"customPdfParse": True})},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "invalid_chunk_settings"}}
    assert fake_fastgpt.call_history == []
    assert _source_count(api_session_factory) == 0


def test_verified_custom_pdf_parse_is_allowed_for_preview_and_ingestion(
    client: TestClient,
    fake_fastgpt,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SUPPORTS_CUSTOM_PDF_PARSE", "true")
    get_settings.cache_clear()
    workspace = client.post("/api/workspaces", json={"title": "Verified PDF"}).json()
    files = {"file": ("notes.txt", b"Mean is an average.", "text/plain")}
    settings = {"settings": json.dumps({"customPdfParse": True})}

    preview = client.post(
        f"/api/workspaces/{workspace['id']}/source-previews/file",
        files=files,
        data=settings,
    )
    ingestion = client.post(
        f"/api/workspaces/{workspace['id']}/sources/file",
        files=files,
        data=settings,
    )

    assert preview.status_code == 200
    assert ingestion.status_code == 201
    assert fake_fastgpt.create_dataset_calls == [("Verified PDF", None, None, None)]
    assert len(fake_fastgpt.create_file_collection_calls) == 1


@pytest.mark.parametrize("model_field", ["vector_model", "agent_model", "vlm_model"])
def test_disabled_workspace_model_is_rejected_before_fastgpt(
    client: TestClient,
    fake_fastgpt,
    model_field: str,
) -> None:
    response = client.post(
        "/api/workspaces",
        json={"title": "RAG", model_field: "verified-model"},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "unsupported_workspace_model"}}
    assert fake_fastgpt.create_dataset_calls == []


def test_model_capability_reports_explicitly_enabled_flags(
    model_capable_client: TestClient,
) -> None:
    response = model_capable_client.get("/api/capabilities/source-ingestion")

    assert response.status_code == 200
    assert response.json()["workspace_models"] == [
        {"key": "vector_model", "supported": True, "disabled_reason": None},
        {"key": "agent_model", "supported": True, "disabled_reason": None},
        {"key": "vlm_model", "supported": True, "disabled_reason": None},
    ]


def _source_count(session_factory: Callable[[], object]) -> int:
    with session_factory() as session:
        return session.scalar(select(func.count(Source.id)))
