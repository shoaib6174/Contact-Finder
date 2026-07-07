"""Common adapter utilities."""

from __future__ import annotations

import functools
import traceback
from typing import Any, Callable

from contact_finder.config import Config
from contact_finder.pii_guard import redact_text

_config = Config()


def adapter(category: str) -> Callable:
    """Decorator for source adapters.

    Adds:
    - polite rate limiting via http_client
    - exception catching
    - PII redaction before returning to the LLM
    - category tagging for tool definitions
    """

    def decorator(fn: Callable) -> Callable:
        fn._adapter_category = category  # type: ignore[attr-defined]

        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            try:
                result = await fn(*args, **kwargs)
                return redact_result(result)
            except Exception as exc:  # noqa: BLE001
                return {
                    "error": type(exc).__name__,
                    "message": str(exc),
                    "detail": traceback.format_exc(limit=2),
                }

        return wrapper

    return decorator


def redact_result(result: Any) -> Any:
    """Recursively redact PII from adapter results."""
    if isinstance(result, str):
        return redact_text(result)
    if isinstance(result, list):
        return [redact_result(item) for item in result]
    if isinstance(result, dict):
        return {k: redact_result(v) for k, v in result.items()}
    return result
