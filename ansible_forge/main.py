"""AnsibleForge application entry point."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from ansible_forge import __version__
from ansible_forge.api.middleware.logging import RequestLoggingMiddleware
from ansible_forge.api.router import api_router
from ansible_forge.config import get_settings
from ansible_forge.logging import get_logger, setup_logging

logger = get_logger(__name__)

UI_DIST = Path(__file__).resolve().parent.parent / "ui" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    setup_logging(settings.log_level)
    logger.info(
        "ansibleforge_starting",
        version=__version__,
        llm_provider=settings.llm_provider,
        llm_model=settings.llm_model,
    )
    yield
    logger.info("ansibleforge_shutdown")


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings.log_level)

    app = FastAPI(
        title="AnsibleForge",
        description=(
            "The definitive AI agent harness for Ansible. "
            "Generate, validate, execute, and manage any Ansible workflow "
            "through natural language."
        ),
        version=__version__,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestLoggingMiddleware)

    app.include_router(api_router)

    if UI_DIST.is_dir():
        app.mount("/assets", StaticFiles(directory=UI_DIST / "assets"), name="ui-assets")

        @app.get("/{full_path:path}")
        async def serve_spa(full_path: str) -> FileResponse:
            """Serve the SPA index.html for all non-API routes."""
            file_path = UI_DIST / full_path
            if file_path.is_file():
                return FileResponse(file_path)
            return FileResponse(UI_DIST / "index.html")

    return app


app = create_app()


def cli_entry() -> None:
    """CLI entry point for `ansible-forge` command."""
    settings = get_settings()
    uvicorn.run(
        "ansible_forge.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        log_level=settings.log_level,
    )


if __name__ == "__main__":
    cli_entry()
