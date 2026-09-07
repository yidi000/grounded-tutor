from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from grounded_tutor.adapters.fakes import FakeFastGPT, FakeGeneration
from grounded_tutor.adapters.fastgpt import FastGPTClient, FastGPTPort
from grounded_tutor.adapters.generation import (
    GenerationPort,
    OpenAICompatibleGenerationClient,
)
from grounded_tutor.config import get_settings
from grounded_tutor.db import engine, ensure_database_is_current
from grounded_tutor.middleware import DemoReadOnlyMiddleware, PreviewRequestBodyLimitMiddleware
from grounded_tutor.routers.admin_evals import router as admin_evals_router
from grounded_tutor.routers.capabilities import router as capabilities_router
from grounded_tutor.routers.chat import router as chat_router
from grounded_tutor.routers.diagnostics import router as diagnostics_router
from grounded_tutor.routers.plans import router as plans_router
from grounded_tutor.routers.previews import router as previews_router
from grounded_tutor.routers.sources import router as sources_router
from grounded_tutor.routers.workspaces import router as workspaces_router
from grounded_tutor.services.source_locks import WorkspaceLockRegistry


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    ensure_database_is_current(engine)
    settings = get_settings()
    fastgpt: FastGPTPort
    generation: GenerationPort
    if settings.external_mode == "live":
        fastgpt = FastGPTClient(
            settings.fastgpt_base_url,
            settings.fastgpt_api_key.get_secret_value(),
        )
        generation = OpenAICompatibleGenerationClient(
            settings.llm_base_url,
            settings.llm_api_key.get_secret_value(),
            settings.llm_model,
        )
    else:
        fastgpt = FakeFastGPT()
        generation = FakeGeneration()
    application.state.fastgpt = fastgpt
    application.state.generation = generation
    application.state.source_locks = WorkspaceLockRegistry()
    try:
        yield
    finally:
        try:
            if isinstance(fastgpt, FastGPTClient):
                await fastgpt.aclose()
        finally:
            if isinstance(generation, OpenAICompatibleGenerationClient):
                await generation.aclose()


app = FastAPI(title="Grounded Tutor API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    PreviewRequestBodyLimitMiddleware,
    settings_provider=get_settings,
)
app.add_middleware(
    DemoReadOnlyMiddleware,
    settings_provider=get_settings,
)
app.include_router(capabilities_router)
app.include_router(workspaces_router)
app.include_router(previews_router)
app.include_router(sources_router)
app.include_router(chat_router)
app.include_router(diagnostics_router)
app.include_router(plans_router)
app.include_router(admin_evals_router)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(
    request: Request, error: RequestValidationError
) -> JSONResponse:
    del request, error
    return JSONResponse(
        status_code=422,
        content={"detail": {"code": "validation_error"}},
    )


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
