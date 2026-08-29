"""Structured service errors shared by HTTP and application layers."""

from __future__ import annotations

from typing import Any


class ServiceError(Exception):
    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or {}


def bad_request(code: str, message: str, **details: Any) -> ServiceError:
    return ServiceError(status_code=400, code=code, message=message, details=details)


def not_found(code: str, message: str, **details: Any) -> ServiceError:
    return ServiceError(status_code=404, code=code, message=message, details=details)
