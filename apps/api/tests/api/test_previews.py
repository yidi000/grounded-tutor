import json
from collections.abc import Callable
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select

import grounded_tutor.main as main_module
from grounded_tutor.adapters.fakes import FakeFastGPT
from grounded_tutor.config import Settings, get_settings
from grounded_tutor.domain.models import Source, Workspace

FIXTURES = Path(__file__).parents[1] / "fixtures"


def test_text_preview_returns_estimated_chunks_for_existing_workspace(
    client: TestClient,
    seeded_workspace: Workspace,
) -> None:
    response = client.post(
        f"/api/workspaces/{seeded_workspace.id}/source-previews/text",
        json={
            "source_name": "Week 1 notes",
            "text": "Mean is an average.\n---\nMedian is the middle value.",
            "settings": {
                "trainingType": "chunk",
                "indexPrefixTitle": True,
                "customPdfParse": False,
                "chunkSettingMode": "custom",
                "chunkSplitMode": "char",
                "chunkSize": 1000,
                "indexSize": 256,
                "chunkSplitter": "---",
                "qaPrompt": "",
            },
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "authority": "estimated",
        "source_name": "Week 1 notes",
        "character_count": 51,
        "items": [
            {
                "position": 1,
                "text": "Mean is an average.",
                "character_count": 19,
                "truncated": False,
                "locator": None,
            },
            {
                "position": 2,
                "text": "Median is the middle value.",
                "character_count": 27,
                "truncated": False,
                "locator": None,
            },
        ],
        "warnings": [],
    }


def test_file_preview_accepts_strict_settings_json_in_multipart(
    client: TestClient,
    seeded_workspace: Workspace,
) -> None:
    response = client.post(
        f"/api/workspaces/{seeded_workspace.id}/source-previews/file",
        files={"file": ("statistics.txt", b"Mean.\n\nMedian.", "text/plain")},
        data={
            "settings": json.dumps(
                {
                    "trainingType": "qa",
                    "chunkSettingMode": "auto",
                    "chunkSplitMode": "paragraph",
                    "chunkSize": 1000,
                    "indexSize": 256,
                }
            )
        },
    )

    assert response.status_code == 200
    assert response.json()["source_name"] == "statistics.txt"
    assert [item["text"] for item in response.json()["items"]] == ["Mean.", "Median."]
    assert response.json()["warnings"] == [{"code": "qa_generated_after_processing"}]


def test_office_preview_returns_estimated_typed_locations(
    client: TestClient,
    seeded_workspace: Workspace,
) -> None:
    pptx = client.post(
        f"/api/workspaces/{seeded_workspace.id}/source-previews/file",
        files={"file": ("slides.pptx", (FIXTURES / "slides.pptx").read_bytes())},
        data={"settings": "{}"},
    )
    xlsx = client.post(
        f"/api/workspaces/{seeded_workspace.id}/source-previews/file",
        files={"file": ("scores.xlsx", (FIXTURES / "workbook.xlsx").read_bytes())},
        data={"settings": "{}"},
    )

    assert pptx.status_code == 200
    assert pptx.json()["authority"] == "estimated"
    assert pptx.json()["items"][0]["locator"] == {
        "kind": "pptx",
        "slide": 1,
        "title": "Chunking",
    }
    assert xlsx.status_code == 200
    assert xlsx.json()["items"][0]["locator"] == {
        "kind": "xlsx",
        "sheet": "Week 1",
        "cell_range": "A1:B3",
    }


def test_image_preview_is_disabled_by_default_and_enabled_by_setting(
    client: TestClient,
    seeded_workspace: Workspace,
) -> None:
    content = (FIXTURES / "diagram.png").read_bytes()
    disabled = client.post(
        f"/api/workspaces/{seeded_workspace.id}/source-previews/file",
        files={"file": ("diagram.png", content, "image/png")},
        data={"settings": "{}"},
    )
    client.app.dependency_overrides[get_settings] = lambda: Settings(
        supports_image_files=True
    )
    enabled = client.post(
        f"/api/workspaces/{seeded_workspace.id}/source-previews/file",
        files={"file": ("diagram.png", content, "image/png")},
        data={"settings": "{}"},
    )

    assert disabled.status_code == 415
    assert enabled.status_code == 200
    assert enabled.json()["items"] == [
        {
            "position": 1,
            "text": "PNG image, 64 x 32 pixels",
            "character_count": 25,
            "truncated": False,
            "locator": {"kind": "image", "filename": "diagram.png", "region": None},
        }
    ]


def test_preview_openapi_exposes_only_exact_fastgpt_setting_aliases(
    client: TestClient,
) -> None:
    schema = client.get("/openapi.json").json()["components"]["schemas"]["ChunkSettings"]

    assert set(schema["properties"]) == {
        "trainingType",
        "indexPrefixTitle",
        "customPdfParse",
        "chunkSettingMode",
        "chunkSplitMode",
        "chunkSize",
        "indexSize",
        "chunkSplitter",
        "qaPrompt",
    }
    assert schema["additionalProperties"] is False


def test_text_preview_qa_mode_never_returns_invented_qa_fields(
    client: TestClient,
    seeded_workspace: Workspace,
) -> None:
    response = client.post(
        f"/api/workspaces/{seeded_workspace.id}/source-previews/text",
        json={
            "source_name": "notes",
            "text": "Mean is an average.",
            "settings": {"trainingType": "qa"},
        },
    )

    assert response.status_code == 200
    assert set(response.json()["items"][0]) == {
        "position",
        "text",
        "character_count",
        "truncated",
        "locator",
    }
    assert response.json()["warnings"] == [{"code": "qa_generated_after_processing"}]


def test_preview_is_read_only_and_never_calls_fastgpt(
    client: TestClient,
    seeded_workspace: Workspace,
    api_session_factory: Callable[[], object],
    fake_fastgpt: FakeFastGPT,
) -> None:
    response = client.post(
        f"/api/workspaces/{seeded_workspace.id}/source-previews/text",
        json={"source_name": "notes", "text": "Mean.", "settings": {}},
    )

    assert response.status_code == 200
    with api_session_factory() as session:
        assert session.scalar(select(func.count(Source.id))) == 0
    assert fake_fastgpt.create_file_collection_calls == []
    assert fake_fastgpt.create_text_collection_calls == []
    assert fake_fastgpt.set_collection_forbidden_calls == []


def test_preview_response_never_exposes_dataset_or_credentials(
    client: TestClient,
    seeded_workspace: Workspace,
) -> None:
    response = client.post(
        f"/api/workspaces/{seeded_workspace.id}/source-previews/text",
        json={"source_name": "notes", "text": "Mean.", "settings": {}},
    )

    public = response.text
    assert response.status_code == 200
    assert seeded_workspace.dataset_id not in public
    assert "dataset_id" not in public
    assert "api_key" not in public


def test_file_preview_enforces_configured_upload_limit(
    client: TestClient,
    seeded_workspace: Workspace,
) -> None:
    main_module.app.dependency_overrides[get_settings] = lambda: Settings(max_upload_bytes=4)

    response = client.post(
        f"/api/workspaces/{seeded_workspace.id}/source-previews/file",
        files={"file": ("statistics.txt", b"12345", "text/plain")},
        data={"settings": "{}"},
    )

    assert response.status_code == 413
    assert response.json() == {"detail": {"code": "file_too_large"}}


def test_file_preview_returns_stable_safe_parser_error(
    client: TestClient,
    seeded_workspace: Workspace,
) -> None:
    response = client.post(
        f"/api/workspaces/{seeded_workspace.id}/source-previews/file",
        files={
            "file": (
                "private-marker.pdf",
                b"%PDF private-content-marker",
                "application/pdf",
            )
        },
        data={"settings": "{}"},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "unreadable_file"}}
    assert "private-content-marker" not in response.text


def test_file_preview_rejects_unsupported_type_with_stable_error(
    client: TestClient,
    seeded_workspace: Workspace,
) -> None:
    response = client.post(
        f"/api/workspaces/{seeded_workspace.id}/source-previews/file",
        files={"file": ("private-marker.exe", b"private-content-marker")},
        data={"settings": "{}"},
    )

    assert response.status_code == 415
    assert response.json() == {"detail": {"code": "unsupported_file_type"}}
    assert "private-content-marker" not in response.text


def test_malformed_multipart_settings_return_stable_validation_error(
    client: TestClient,
    seeded_workspace: Workspace,
) -> None:
    response = client.post(
        f"/api/workspaces/{seeded_workspace.id}/source-previews/file",
        files={"file": ("notes.txt", b"Mean.")},
        data={"settings": '{"indexPrefixTitle":"private-marker"}'},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "invalid_chunk_settings"}}
    assert "private-marker" not in response.text


def test_http_settings_reject_internal_python_field_names(
    client: TestClient,
    seeded_workspace: Workspace,
) -> None:
    text_response = client.post(
        f"/api/workspaces/{seeded_workspace.id}/source-previews/text",
        json={
            "source_name": "notes",
            "text": "Mean.",
            "settings": {"training_type": "qa"},
        },
    )
    file_response = client.post(
        f"/api/workspaces/{seeded_workspace.id}/source-previews/file",
        files={"file": ("notes.txt", b"Mean.")},
        data={"settings": '{"training_type":"qa"}'},
    )

    assert text_response.status_code == 422
    assert file_response.status_code == 422
    assert file_response.json() == {"detail": {"code": "invalid_chunk_settings"}}


def test_text_request_rejects_unknown_and_malformed_fields(
    client: TestClient,
    seeded_workspace: Workspace,
) -> None:
    response = client.post(
        f"/api/workspaces/{seeded_workspace.id}/source-previews/text",
        json={
            "source_name": "notes",
            "text": 123,
            "settings": {},
            "dataset_id": "dataset-private-marker",
        },
    )

    assert response.status_code == 422
    assert "dataset-private-marker" not in response.text


def test_empty_text_returns_a_stable_error(
    client: TestClient,
    seeded_workspace: Workspace,
) -> None:
    response = client.post(
        f"/api/workspaces/{seeded_workspace.id}/source-previews/text",
        json={"source_name": "notes", "text": " \n ", "settings": {}},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "empty_source"}}


def test_text_source_name_is_trimmed_and_bounded(
    client: TestClient,
    seeded_workspace: Workspace,
) -> None:
    success = client.post(
        f"/api/workspaces/{seeded_workspace.id}/source-previews/text",
        json={"source_name": "  notes  ", "text": "Mean.", "settings": {}},
    )
    too_long = client.post(
        f"/api/workspaces/{seeded_workspace.id}/source-previews/text",
        json={"source_name": "x" * 256, "text": "Mean.", "settings": {}},
    )

    assert success.status_code == 200
    assert success.json()["source_name"] == "notes"
    assert too_long.status_code == 422


def test_missing_or_invalid_workspace_is_hidden_behind_not_found(
    client: TestClient,
) -> None:
    for workspace_id in ["not-a-uuid", "00000000-0000-0000-0000-000000000000"]:
        text_response = client.post(
            f"/api/workspaces/{workspace_id}/source-previews/text",
            json={"source_name": "notes", "text": "Mean.", "settings": {}},
        )
        file_response = client.post(
            f"/api/workspaces/{workspace_id}/source-previews/file",
            files={"file": ("notes.txt", b"Mean.")},
            data={"settings": "{}"},
        )

        assert text_response.status_code == 404
        assert text_response.json() == {"detail": {"code": "workspace_not_found"}}
        assert file_response.status_code == 404
        assert file_response.json() == {"detail": {"code": "workspace_not_found"}}
