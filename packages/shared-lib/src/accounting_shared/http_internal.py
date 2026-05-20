"""Service-to-service JSON POST (stdlib urllib; avoids httpx localhost issues on Windows)."""

from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request
from typing import Any


async def post_json(
    url: str,
    *,
    headers: dict[str, str],
    body: dict[str, Any],
    timeout: float = 10.0,
) -> tuple[int, Any]:
    """POST JSON and return ``(status_code, parsed_json_or_text)``."""

    def _send() -> tuple[int, Any]:
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={**headers, "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                status = resp.status
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            status = exc.code
            raw = exc.read()
        try:
            parsed: Any = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            parsed = raw.decode("utf-8", errors="replace")
        return status, parsed

    return await asyncio.to_thread(_send)
