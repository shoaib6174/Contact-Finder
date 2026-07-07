"""Polite HTTP client with in-memory caching and retries."""

from __future__ import annotations

import asyncio
import time
from functools import wraps
from typing import Any, Callable

import httpx

from contact_finder.config import Config

_config = Config()

# module-level in-memory cache: {(method, url, sorted_params): response_content}
_cache: dict[tuple, Any] = {}


async def get(
    url: str,
    params: dict | None = None,
    headers: dict | None = None,
    follow_redirects: bool = True,
    timeout: float = 30.0,
    use_cache: bool = True,
) -> httpx.Response:
    """Perform a polite GET with optional caching and rate limiting."""
    key = ("GET", url, tuple(sorted((params or {}).items())))
    if use_cache and key in _cache:
        return _cache[key]

    await asyncio.sleep(_config.request_delay)

    default_headers = {"User-Agent": _config.user_agent}
    if headers:
        default_headers.update(headers)

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=follow_redirects) as client:
        resp = await client.get(url, params=params, headers=default_headers)
        resp.raise_for_status()

    if use_cache:
        _cache[key] = resp
    return resp


async def post(
    url: str,
    json: dict | None = None,
    headers: dict | None = None,
    timeout: float = 30.0,
) -> httpx.Response:
    """Perform a polite POST."""
    await asyncio.sleep(_config.request_delay)

    default_headers = {"User-Agent": _config.user_agent, "Content-Type": "application/json"}
    if headers:
        default_headers.update(headers)

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, json=json, headers=default_headers)
        resp.raise_for_status()
    return resp


def clear_cache() -> None:
    """Clear the in-memory cache. Called at end of run."""
    _cache.clear()


def cached_adapter(fn: Callable) -> Callable:
    """Decorator that adds polite delay + caching for adapter calls."""

    @wraps(fn)
    async def wrapper(*args, **kwargs):
        key = (fn.__name__, args, tuple(sorted(kwargs.items())))
        if key in _cache:
            return _cache[key]

        await asyncio.sleep(_config.request_delay)
        result = await fn(*args, **kwargs)
        _cache[key] = result
        return result

    return wrapper
