"""Thin Groq client wrapper with optional secondary API key fallback."""

from __future__ import annotations

from groq import AsyncGroq

from contact_finder.config import Config


def _is_rate_limit(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in ["rate limit", "429", "limit", "tokens per", "tpm", "tpd"])


async def chat_completion(config: Config, **kwargs):
    """Call Groq chat.completions.create, falling back to key #2 on rate limit."""
    client = AsyncGroq(api_key=config.groq_api_key)
    try:
        return await client.chat.completions.create(**kwargs)
    except Exception as exc:  # noqa: BLE001
        if config.groq_api_key_2 and _is_rate_limit(exc):
            client2 = AsyncGroq(api_key=config.groq_api_key_2)
            return await client2.chat.completions.create(**kwargs)
        raise
