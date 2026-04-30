"""Request/response logging middleware with request-ID propagation."""

from __future__ import annotations

import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from ansible_forge.logging import get_logger

logger = get_logger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
        start = time.monotonic()
        method = request.method
        path = request.url.path

        logger.info("request_start", method=method, path=path, request_id=request_id)

        try:
            response = await call_next(request)
        except Exception:
            logger.exception("request_error", method=method, path=path, request_id=request_id)
            raise

        elapsed_ms = round((time.monotonic() - start) * 1000, 1)
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "request_end",
            method=method,
            path=path,
            status=response.status_code,
            elapsed_ms=elapsed_ms,
            request_id=request_id,
        )
        return response
