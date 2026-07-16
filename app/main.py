"""
ThirdPersona: Single-User Vertical Slice

FastAPI app with RLS-enforced entry ingestion and
candidate → hypothesis → active pattern lifecycle.
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import init_pool, close_pool
from app.routers import entries, patterns


@asynccontextmanager
async def lifespan(app: FastAPI):
    # No auto-migration here — deliberately. Migrations need owner
    # privileges; the runtime connects as a non-superuser role so RLS
    # actually applies. Run `python scripts/setup_db.py` (admin DSN)
    # before starting the app. init_pool refuses to boot if the runtime
    # role is SUPERUSER or BYPASSRLS.
    await init_pool(settings.database_url)
    yield
    await close_pool()


app = FastAPI(
    title="ThirdPersona",
    description="Single-user vertical slice: entry → pattern → hypothesis → active",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS: lets the standalone demo (opened as a local file) talk to this API.
# Fine for the single-user vertical slice; lock down origins before any
# multi-user deployment.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(entries.router)
app.include_router(patterns.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
