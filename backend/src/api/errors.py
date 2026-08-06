"""Application-wide machine-readable API error contract."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from time import perf_counter
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from src.api.schemas.error import ApiErrorResponse


LOGGER = logging.getLogger(__name__)
REQUEST_LOGGER = logging.getLogger("uvicorn.error")
TRACE_ID_HEADER = "X-Trace-Id"
MACHINE_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+$")

ERROR_RESPONSES = {
    status: {"model": ApiErrorResponse, "description": "Machine-readable API error"}
    for status in (400, 401, 403, 404, 409, 413, 422, 500, 502)
}


class DomainError(ValueError):
    """Expected domain failure that is safe to expose as code plus parameters."""

    def __init__(
        self,
        code: str,
        params: Mapping[str, Any] | None = None,
        http_status: int = 400,
    ) -> None:
        if not MACHINE_CODE_PATTERN.fullmatch(code):
            raise ValueError(f"Invalid domain error code: {code!r}")
        super().__init__(code)
        self.code = code
        self.params = dict(params or {})
        self.http_status = http_status


def domain_error_from_exception(
    error: Exception,
    fallback_code: str,
    *,
    params: Mapping[str, Any] | None = None,
    http_status: int = 400,
) -> DomainError:
    """Preserve a service machine code, otherwise replace its text with a stable fallback."""

    if isinstance(error, DomainError):
        return error
    candidate = str(error)
    code = candidate if MACHINE_CODE_PATTERN.fullmatch(candidate) else fallback_code
    return DomainError(code=code, params=params, http_status=http_status)


def install_error_handlers(app: FastAPI) -> None:
    """Install trace-id middleware and all public exception boundaries."""

    @app.middleware("http")
    async def attach_trace_id(request: Request, call_next):
        request.state.trace_id = f"req_{uuid4().hex}"
        started_at = perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers[TRACE_ID_HEADER] = request.state.trace_id
            return response
        finally:
            duration_ms = round((perf_counter() - started_at) * 1000, 1)
            REQUEST_LOGGER.info(
                "API request completed method=%s route=%s status=%d durationMs=%.1f traceId=%s",
                request.method,
                request.url.path,
                status_code,
                duration_ms,
                request.state.trace_id,
                extra={
                    "method": request.method,
                    "route": request.url.path,
                    "status": status_code,
                    "durationMs": duration_ms,
                    "traceId": request.state.trace_id,
                },
            )

    @app.exception_handler(DomainError)
    async def handle_domain_error(request: Request, error: DomainError) -> JSONResponse:
        return error_response(request, error.code, error.params, error.http_status)

    @app.exception_handler(RequestValidationError)
    async def handle_request_validation(request: Request, error: RequestValidationError) -> JSONResponse:
        field_errors = [
            {
                "path": list(item.get("loc", ())),
                "code": f"request.validation.{item.get('type', 'invalid')}",
                "params": {
                    key: public_json_value(value)
                    for key, value in dict(item.get("ctx") or {}).items()
                    if key != "error"
                },
            }
            for item in error.errors()
        ]
        return error_response(
            request,
            "request.validation_failed",
            {"errors": field_errors},
            422,
        )

    @app.exception_handler(HTTPException)
    async def handle_http_exception(request: Request, error: HTTPException) -> JSONResponse:
        detail = error.detail
        if isinstance(detail, Mapping) and isinstance(detail.get("code"), str):
            code = detail["code"]
            params = detail.get("params")
            if MACHINE_CODE_PATTERN.fullmatch(code) and isinstance(params, Mapping):
                return error_response(request, code, params, error.status_code)
        return error_response(
            request,
            http_status_code(error.status_code),
            {},
            error.status_code,
        )

    @app.exception_handler(Exception)
    async def handle_unknown_error(request: Request, error: Exception) -> JSONResponse:
        trace_id = trace_id_for(request)
        LOGGER.exception(
            "Unhandled API exception",
            extra={
                "errorCode": "common.internal_error",
                "traceId": trace_id,
                "route": request.url.path,
            },
        )
        return error_response(request, "common.internal_error", {}, 500)


def error_response(
    request: Request,
    code: str,
    params: Mapping[str, Any],
    status_code: int,
) -> JSONResponse:
    trace_id = trace_id_for(request)
    body = ApiErrorResponse.model_validate(
        {
            "error": {
                "code": code,
                "params": public_json_value(dict(params)),
                "traceId": trace_id,
            }
        }
    )
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(mode="json"),
        headers={TRACE_ID_HEADER: trace_id},
    )


def trace_id_for(request: Request) -> str:
    trace_id = getattr(request.state, "trace_id", None)
    if isinstance(trace_id, str) and trace_id:
        return trace_id
    trace_id = f"req_{uuid4().hex}"
    request.state.trace_id = trace_id
    return trace_id


def http_status_code(status_code: int) -> str:
    return {
        400: "request.bad_request",
        401: "auth.unauthorized",
        403: "auth.forbidden",
        404: "request.not_found",
        405: "request.method_not_allowed",
        409: "request.conflict",
        413: "request.payload_too_large",
        422: "request.validation_failed",
        429: "request.rate_limited",
    }.get(status_code, "common.internal_error" if status_code >= 500 else "request.failed")


def public_json_value(value: Any) -> Any:
    """Convert explicitly public parameters to JSON-safe values without exception text."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): public_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [public_json_value(item) for item in value]
    return value.__class__.__name__
