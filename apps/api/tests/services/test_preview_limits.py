from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from docx import Document
from pydantic import ValidationError
from pypdf import PdfWriter

import grounded_tutor.services.previews as previews_module
from grounded_tutor.config import Settings
from grounded_tutor.domain.ingestion import ChunkSettings
from grounded_tutor.services.previews import PreviewError, PreviewService, preview_file


class RecordingWorkspaceRepository:
    def __init__(self) -> None:
        self.get_calls = 0

    def get(self, workspace_id):
        self.get_calls += 1
        return object()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_upload_bytes", 0),
        ("max_upload_bytes", -1),
        ("max_upload_bytes", True),
        ("max_preview_text_bytes", 0),
        ("max_preview_text_bytes", -1),
        ("max_preview_text_bytes", True),
        ("max_extracted_characters", 0),
        ("max_extracted_characters", -1),
        ("max_extracted_characters", True),
    ],
)
def test_preview_resource_limits_must_be_strictly_positive(
    field: str, value: int | bool
) -> None:
    with pytest.raises(ValidationError):
        Settings(**{field: value})


def test_multibyte_text_byte_budget_is_checked_before_workspace_lookup() -> None:
    repository = RecordingWorkspaceRepository()
    service = PreviewService(
        repository,
        max_upload_bytes=100,
        max_preview_text_bytes=4,
        max_extracted_characters=100,
    )

    with pytest.raises(PreviewError) as caught:
        service.from_text(
            "00000000-0000-0000-0000-000000000000",
            source_name="notes",
            text="界界",
            settings=ChunkSettings(),
        )

    assert caught.value.code == "text_too_large"
    assert repository.get_calls == 0


def test_text_character_budget_is_checked_before_workspace_lookup() -> None:
    repository = RecordingWorkspaceRepository()
    service = PreviewService(
        repository,
        max_upload_bytes=100,
        max_preview_text_bytes=100,
        max_extracted_characters=3,
    )

    with pytest.raises(PreviewError) as caught:
        service.from_text(
            "00000000-0000-0000-0000-000000000000",
            source_name="notes",
            text="four",
            settings=ChunkSettings(),
        )

    assert caught.value.code == "source_too_large"
    assert repository.get_calls == 0


def test_file_byte_budget_is_checked_before_workspace_lookup() -> None:
    repository = RecordingWorkspaceRepository()
    service = PreviewService(
        repository,
        max_upload_bytes=4,
        max_preview_text_bytes=100,
        max_extracted_characters=100,
    )

    with pytest.raises(PreviewError) as caught:
        service.from_file(
            "00000000-0000-0000-0000-000000000000",
            filename="notes.txt",
            content=b"12345",
            settings=ChunkSettings(),
        )

    assert caught.value.code == "file_too_large"
    assert repository.get_calls == 0


@pytest.mark.parametrize(
    ("filename", "content"),
    [
        ("large.txt", b"12345"),
        ("large.html", b"<p>12345</p>"),
        ("large.csv", b"1,2,3"),
    ],
)
def test_plain_extractors_share_the_extracted_character_budget(
    filename: str, content: bytes
) -> None:
    with pytest.raises(PreviewError) as caught:
        preview_file(
            filename,
            content,
            ChunkSettings(),
            max_upload_bytes=100,
            max_extracted_characters=4,
        )

    assert caught.value.code == "source_too_large"


def test_exact_20_mb_text_file_remains_within_the_supported_file_limit() -> None:
    preview = preview_file(
        "large-valid.txt",
        b"x" * 20_000_000,
        ChunkSettings(),
        max_upload_bytes=20_000_000,
    )

    assert preview.character_count == 20_000_000
    assert preview.items[0].text == "x" * 500


def test_small_highly_compressed_docx_is_rejected_before_python_docx_expands_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = Document()
    document.add_paragraph("A" * 3_000_000)
    output = BytesIO()
    document.save(output)
    assert len(output.getvalue()) < 100_000
    monkeypatch.setattr(
        previews_module,
        "Document",
        lambda stream: (_ for _ in ()).throw(
            AssertionError("python-docx must not open an unsafe archive")
        ),
    )

    with pytest.raises(PreviewError) as caught:
        preview_file(
            "compressed.docx",
            output.getvalue(),
            ChunkSettings(),
            max_upload_bytes=20_000_000,
        )

    assert caught.value.code == "unsafe_archive"


def test_docx_with_excessive_archive_members_is_rejected() -> None:
    document = Document()
    document.add_paragraph("Mean is an average.")
    output = BytesIO()
    document.save(output)
    with ZipFile(output, "a", compression=ZIP_DEFLATED) as archive:
        for index in range(1001):
            archive.writestr(f"customXml/extra-{index}.xml", "x")

    with pytest.raises(PreviewError) as caught:
        preview_file(
            "many-members.docx",
            output.getvalue(),
            ChunkSettings(),
            max_upload_bytes=20_000_000,
        )

    assert caught.value.code == "unsafe_archive"


def test_docx_extracted_node_budget_is_deterministic() -> None:
    document = Document()
    for index in range(10_001):
        document.add_paragraph(f"Paragraph {index}")
    output = BytesIO()
    document.save(output)

    with pytest.raises(PreviewError) as caught:
        preview_file(
            "many-blocks.docx",
            output.getvalue(),
            ChunkSettings(),
            max_upload_bytes=20_000_000,
        )

    assert caught.value.code == "source_work_limit_exceeded"


def test_docx_table_work_budget_is_checked_before_reading_oversized_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = Document()
    document.add_paragraph("valid archive")
    output = BytesIO()
    document.save(output)

    class UnreadableCell:
        @property
        def text(self) -> str:
            raise AssertionError("cell text must not be read after work budget is exceeded")

    class OversizedRow:
        cells = (UnreadableCell(),) * 10_001

    class OversizedTable:
        rows = (OversizedRow(),)

    class FakeDocument:
        def iter_inner_content(self):
            yield OversizedTable()

    monkeypatch.setattr(previews_module, "Document", lambda stream: FakeDocument())
    monkeypatch.setattr(previews_module, "Table", OversizedTable)

    with pytest.raises(PreviewError) as caught:
        preview_file(
            "oversized-table.docx",
            output.getvalue(),
            ChunkSettings(),
            max_upload_bytes=20_000_000,
        )

    assert caught.value.code == "source_work_limit_exceeded"


def test_pdf_page_budget_is_checked_before_text_extraction() -> None:
    writer = PdfWriter()
    for _ in range(501):
        writer.add_blank_page(width=100, height=100)
    output = BytesIO()
    writer.write(output)

    with pytest.raises(PreviewError) as caught:
        preview_file(
            "many-pages.pdf",
            output.getvalue(),
            ChunkSettings(),
            max_upload_bytes=20_000_000,
        )

    assert caught.value.code == "source_work_limit_exceeded"


def test_pdf_extracted_text_uses_the_shared_character_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakePage:
        def extract_text(self) -> str:
            return "12345"

    class FakeReader:
        is_encrypted = False
        pages = (FakePage(),)

    monkeypatch.setattr(previews_module, "PdfReader", lambda stream: FakeReader())

    with pytest.raises(PreviewError) as caught:
        preview_file(
            "bounded.pdf",
            b"%PDF-valid-for-test-double",
            ChunkSettings(),
            max_upload_bytes=100,
            max_extracted_characters=4,
        )

    assert caught.value.code == "source_too_large"
