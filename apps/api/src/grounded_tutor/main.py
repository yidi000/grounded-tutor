from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from grounded_tutor.adapters.fakes import FakeFastGPT
from grounded_tutor.adapters.fastgpt import FastGPTClient, FastGPTPort
from grounded_tutor.config import get_settings
from grounded_tutor.db import engine, ensure_database_is_current
from grounded_tutor.routers.workspaces import router as workspaces_router


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    ensure_database_is_current(engine)
    settings = get_settings()
    fastgpt: FastGPTPort
    if settings.external_mode == "live":
        fastgpt = FastGPTClient(
            settings.fastgpt_base_url,
            settings.fastgpt_api_key.get_secret_value(),
        )
    else:
        fastgpt = FakeFastGPT()
    application.state.fastgpt = fastgpt
    try:
        yield
    finally:
        if isinstance(fastgpt, FastGPTClient):
            await fastgpt.aclose()


app = FastAPI(title="Grounded Tutor API", version="0.1.0", lifespan=lifespan)
app.include_router(workspaces_router)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
