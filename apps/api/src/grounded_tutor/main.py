from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from grounded_tutor.db import engine, ensure_database_is_current


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    ensure_database_is_current(engine)
    yield


app = FastAPI(title="Grounded Tutor API", version="0.1.0", lifespan=lifespan)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
