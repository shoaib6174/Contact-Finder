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


_SENSITIVE_KEYS = {
    "email",
    "phone",
    "phone_number",
    "address",
    "snippet",
    "body",
    "raw_evidence",
    "evidence",
}


def _is_sensitive_key(key: str) -> bool:
    lower = key.lower()
    return any(marker in lower for marker in _SENSITIVE_KEYS)


def redact_result(result: Any) -> Any:
    """Recursively redact PII from adapter results, preserving titles/names."""
    if isinstance(result, str):
        return redact_text(result)
    if isinstance(result, list):
        return [redact_result(item) for item in result]
    if isinstance(result, dict):
        cleaned = {}
        for k, v in result.items():
            if _is_sensitive_key(k):
                cleaned[k] = redact_result(v)
            else:
                # Recurse into nested structures but keep bare strings intact.
                if isinstance(v, (list, dict)):
                    cleaned[k] = redact_result(v)
                else:
                    cleaned[k] = v
        return cleaned
    return result
