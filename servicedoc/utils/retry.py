import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

import httpx

logger = logging.getLogger(__name__)
T = TypeVar("T")


async def retry_async(
    fn: Callable[[], Awaitable[T]],
    *,
    max_attempts: int = 5,
    base_delay: float = 2.0,
    retryable_status: frozenset[int] = frozenset({429, 503}),
) -> T:
    for attempt in range(max_attempts):
        try:
            return await fn()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in retryable_status:
                raise
            if attempt == max_attempts - 1:
                raise
            delay = base_delay * (2**attempt)
            logger.warning(
                "HTTP %s — retry %d/%d in %.1fs",
                exc.response.status_code,
                attempt + 1,
                max_attempts,
                delay,
            )
            await asyncio.sleep(delay)
    raise RuntimeError("retry_async: unreachable")
