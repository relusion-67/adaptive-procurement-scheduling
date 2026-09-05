from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.api_router import api_router
from app.core.config import settings
from app.db.health import can_connect_to_database


def create_application() -> FastAPI:
    application = FastAPI(title=settings.api_title, version=settings.api_version)

    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.backend_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    application.include_router(api_router, prefix=settings.api_prefix)

    @application.get("/")
    async def root() -> dict[str, str]:
        return {"message": "Adaptive Procurement Scheduling API is running -v2"}

    @application.get("/health")
    async def health() -> JSONResponse:
        # Reuses the existing DB health helper (app/db/health.py) so this
        # endpoint reports the same connectivity signal the rest of the app
        # relies on, rather than duplicating the check. Returns 503 with an
        # "unhealthy" body when Postgres can't be reached, 200 otherwise -
        # no other API behavior changes.
        if can_connect_to_database():
            return JSONResponse(status_code=200, content={"status": "healthy"})
        return JSONResponse(
            status_code=503,
            content={"status": "unhealthy", "detail": "database unreachable"},
        )

    return application


app = create_application()
