"""Provider-agnostic LLM client wrapper.

All SDK-specific calls are isolated here so the rest of the app (llm_parser,
llm_explainer) never imports a provider SDK directly. Swapping providers only
means changing this file's internals, not any caller.
"""
import json
import os


class LLMUnavailableError(Exception):
    """Raised when no LLM provider/API key is configured, or the call fails."""


def _get_config() -> tuple[str, str, str]:
    provider = os.environ.get("LLM_PROVIDER", "anthropic")
    api_key = os.environ.get("LLM_API_KEY")
    model = os.environ.get("LLM_MODEL", "claude-sonnet-5")
    if not api_key:
        raise LLMUnavailableError("LLM_API_KEY is not configured")
    return provider, api_key, model


def complete(system_prompt: str, user_prompt: str, *, json_schema: dict | None = None, temperature: float | None = None) -> str:
    """Send a single-turn prompt to the configured LLM provider and return text.

    If json_schema is given, the provider is forced to call a tool whose
    input matches that schema - the API itself returns a parsed JSON object
    (no free text, no markdown fences to strip), which is re-serialized here
    so callers can json.loads() it uniformly.

    temperature: optional override. If None, uses default (0 for schema calls,
    1.0 for text). Pass explicitly to override.

    Raises LLMUnavailableError if not configured or the call fails, so callers
    can degrade gracefully.
    """
    provider, api_key, model = _get_config()

    try:
        if provider == "anthropic":
            return _complete_anthropic(api_key, model, system_prompt, user_prompt, json_schema, temperature)
        raise LLMUnavailableError(f"Unsupported LLM_PROVIDER: {provider}")
    except LLMUnavailableError:
        raise
    except Exception as e:
        raise LLMUnavailableError(f"LLM call failed: {e}") from e


def _complete_anthropic(
    api_key: str, model: str, system_prompt: str, user_prompt: str, json_schema: dict | None, temperature: float | None = None
) -> str:
    # Calls the Anthropic REST API directly over HTTP instead of using the
    # `anthropic` SDK, which depends on the native `jiter` extension - that
    # extension is blocked by this machine's Application Control policy.
    import httpx
    import time

    # Determine max_tokens and temperature based on whether structured output
    # (tool-use with schema) is being used. Structured calls are just extracting
    # JSON from a fixed schema - they need less headroom and zero temperature
    # for determinism. Unstructured text calls get standard tokens and temp.
    max_tokens = 256 if json_schema else 1024
    if temperature is None:
        temperature = 0.0 if json_schema else 1.0

    request_body = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_prompt}],
    }

    if json_schema is not None:
        # Force structured output via tool-use: the API parses the model's
        # output against this schema server-side and returns it as an
        # actual JSON object in a tool_use block, not free text.
        request_body["tools"] = [
            {
                "name": "respond",
                "description": "Provide your structured response.",
                "input_schema": json_schema,
            }
        ]
        request_body["tool_choice"] = {"type": "tool", "name": "respond"}

    max_retries = 1
    for attempt in range(max_retries + 1):
        try:
            response = httpx.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json=request_body,
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()
            break
        except httpx.HTTPStatusError as e:
            # A response did come back, just with a bad status - retry once
            # on transient 5xx or 429 (rate limit).
            if attempt < max_retries and e.response.status_code in (429, 500, 502, 503, 504):
                time.sleep(0.5)
                continue
            raise
        except httpx.RequestError:
            # The request itself never completed (timeout, connection reset,
            # DNS failure, etc.) - there's no response object to inspect here,
            # unlike HTTPStatusError above. Retry once, since these are
            # typically transient too.
            if attempt < max_retries:
                time.sleep(0.5)
                continue
            raise

    if json_schema is not None:
        tool_use = next(block for block in data["content"] if block["type"] == "tool_use")
        return json.dumps(tool_use["input"])

    return "".join(block["text"] for block in data["content"] if block["type"] == "text")
