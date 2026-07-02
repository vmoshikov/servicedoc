from __future__ import annotations

import json
import logging

import httpx
from jinja2 import Template

from servicedoc.config import AIConfig
from servicedoc.models.symbols import Symbol
from servicedoc.utils.retry import retry_async

from .prompts import BATCH_DESCRIBE_SYSTEM, BATCH_DESCRIBE_USER
from .rate_limiter import TokenBucketRateLimiter

logger = logging.getLogger(__name__)


class AIClient:
    def __init__(self, config: AIConfig) -> None:
        self.config = config
        self._http = httpx.AsyncClient(
            base_url=config.base_url,
            headers={"Authorization": f"Bearer {config.api_key}", "Content-Type": "application/json"},
            timeout=120.0,
        )
        self._limiter = TokenBucketRateLimiter(config.rate_limit_rpm)

    async def close(self) -> None:
        await self._http.aclose()

    async def complete(self, system: str, user: str) -> str:
        payload = {
            "model": self.config.model,
            "max_tokens": self.config.max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }

        async def _post() -> str:
            response = await self._http.post("/v1/chat/completions", json=payload)
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]

        await self._limiter.acquire()
        return await retry_async(
            _post,
            max_attempts=self.config.retry_max_attempts,
            base_delay=self.config.retry_base_delay_seconds,
        )

    async def describe_batch(self, symbols: list[Symbol], source_map: dict) -> list[str | None]:
        """Send a batch of symbols for description. Returns list of descriptions."""
        items = []
        for sym in symbols:
            code = source_map.get(sym.file_path, b"")
            if isinstance(code, bytes):
                lines = code.split(b"\n")
                block_lines = lines[sym.line_start - 1: sym.line_end]
                code_block = b"\n".join(block_lines).decode("utf-8", errors="replace")
            else:
                code_block = ""
            items.append({
                "name": sym.name,
                "kind": sym.kind,
                "file_path": str(sym.file_path),
                "line_start": sym.line_start,
                "line_end": sym.line_end,
                "code_block": code_block,
            })

        user_prompt = Template(BATCH_DESCRIBE_USER).render(symbols=items, count=len(items))
        try:
            response = await self.complete(BATCH_DESCRIBE_SYSTEM, user_prompt)
            # parse JSON array from response
            start = response.find("[")
            end = response.rfind("]") + 1
            if start >= 0 and end > start:
                descriptions = json.loads(response[start:end])
                if isinstance(descriptions, list) and len(descriptions) == len(symbols):
                    return descriptions
        except Exception as exc:
            logger.warning("AI batch describe failed: %s", exc)
        return [None] * len(symbols)
