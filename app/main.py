from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from app.routers import dashboard, filter, health
from app.config.settings import settings

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(30.0),
        limits=httpx.Limits(max_keepalive_connections=20, max_connections=100),
        follow_redirects=True,
    ) as client:
        app.state.http_client = client
        yield


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.PROJECT_VERSION,
    lifespan=lifespan,
)

_cors_origins = list(settings.ALLOWED_ORIGINS) if settings.ALLOWED_ORIGINS else ["*"]
# Browsers reject Access-Control-Allow-Origin: * with credentials: true
_cors_credentials = not (
    len(_cors_origins) == 1 and _cors_origins[0] == "*"
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=_cors_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(filter.router)
app.include_router(dashboard.router)
