"""Request/response logging middleware."""

from __future__ import annotations

import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from ansible_forge.logging import get_logger

logger = get_logger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        start = time.monotonic()
        method = request.method
        path = request.url.path

        logger.info("request_start", method=method, path=path)

        try:
            response = await call_next(request)
        except Exception:
            logger.exception("request_error", method=method, path=path)
            raise

        elapsed_ms = round((time.monotonic() - start) * 1000, 1)
        logger.info(
            "request_end",
            method=method,
            path=path,
            status=response.status_code,
            elapsed_ms=elapsed_ms,
        )
        return response
