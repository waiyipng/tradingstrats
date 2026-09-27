"""Shared HTTP helpers for sourcing adapters."""
from __future__ import annotations

import json
from typing import Any

import certifi
import requests


def safe_http_get(url: str, timeout: int = 20, headers: dict[str, str] | None = None) -> bytes:
    response = requests.get(
        url,
        headers={"User-Agent": "tradingstrats/1.0", **(headers or {})},
        timeout=timeout,
        verify=certifi.where(),
    )
    response.raise_for_status()
    return response.content


def safe_json_get(url: str, timeout: int = 20, headers: dict[str, str] | None = None) -> Any:
    return json.loads(safe_http_get(url, timeout=timeout, headers=headers).decode("utf-8", errors="replace"))
