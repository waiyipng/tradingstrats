"""Shared Claude API call for the analyst and trading agents.

Requires ANTHROPIC_API_KEY in the environment. Any SDK failure is converted to
a RuntimeError so callers can degrade the same way they do on an IBKR
market-data failure (status: data_unavailable), rather than crashing.
"""
from __future__ import annotations

import json
import os

import anthropic

MODEL = "claude-opus-5-5"


def call_agent_json(system_prompt: str, user_prompt: str, max_tokens: int = 8192) -> dict:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY is not set; cannot run the agent")

    client = anthropic.Anthropic()
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
            output_config={"effort": "high"},
        )
    except anthropic.AuthenticationError as exc:
        raise RuntimeError(f"Claude API authentication failed: {exc}") from exc
    except anthropic.RateLimitError as exc:
        raise RuntimeError(f"Claude API rate limited: {exc}") from exc
    except anthropic.APIStatusError as exc:
        raise RuntimeError(f"Claude API error ({exc.status_code}): {exc.message}") from exc
    except anthropic.APIConnectionError as exc:
        raise RuntimeError(f"Claude API connection error: {exc}") from exc

    text = next((block.text for block in response.content if block.type == "text"), None)
    if text is None:
        raise RuntimeError("Claude API response contained no text block")

    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned
        if cleaned.endswith("```"):
            cleaned = cleaned.rsplit("```", 1)[0]
        cleaned = cleaned.strip()
        if cleaned.startswith("json"):
            cleaned = cleaned[4:].strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Claude API response was not valid JSON: {exc}") from exc
