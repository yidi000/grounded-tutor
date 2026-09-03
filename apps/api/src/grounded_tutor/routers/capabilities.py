from typing import Annotated

from fastapi import APIRouter, Depends

from grounded_tutor.config import Settings, get_settings
from grounded_tutor.domain.schemas import (
    CapabilityItem,
    SourceIngestionCapabilities,
)
from grounded_tutor.services.previews import SUPPORTED_EXTENSIONS

router = APIRouter(prefix="/api/capabilities", tags=["capabilities"])


def _capability_item(key: str, *, verified: bool, demo: bool) -> CapabilityItem:
    if demo:
        return CapabilityItem(key=key, supported=False, disabled_reason="demo_read_only")
    if verified:
        return CapabilityItem(key=key, supported=True, disabled_reason=None)
    return CapabilityItem(
        key=key,
        supported=False,
        disabled_reason="deployment_not_verified",
    )


@router.get("/source-ingestion", response_model=SourceIngestionCapabilities)
def source_ingestion_capabilities(
    settings: Annotated[Settings, Depends(get_settings)],
) -> SourceIngestionCapabilities:
    demo = settings.demo_read_only
    return SourceIngestionCapabilities(
        accepted_extensions=sorted(SUPPORTED_EXTENSIONS),
        max_upload_bytes=settings.max_upload_bytes,
        settings=[
            _capability_item(
                "customPdfParse",
                verified=settings.supports_custom_pdf_parse,
                demo=demo,
            ),
            _capability_item(
                "imageFiles",
                verified=settings.supports_image_files,
                demo=demo,
            ),
        ],
        workspace_models=[
            _capability_item(
                "vector_model",
                verified=settings.supports_vector_model,
                demo=demo,
            ),
            _capability_item(
                "agent_model",
                verified=settings.supports_agent_model,
                demo=demo,
            ),
            _capability_item(
                "vlm_model",
                verified=settings.supports_vlm_model,
                demo=demo,
            ),
        ],
        read_only_demo=demo,
    )
