"""LLM access via the OpenAI SDK, pointed at a local llama.cpp server.

Structured output uses llama.cpp's `response_format: json_schema` (GBNF
grammar constrained), so even a small local model returns parseable JSON.
Schemas are derived from the Pydantic model passed in, then tightened for
strict mode.

Two things matter when the model is a small local reasoning model:

1. **It thinks before answering.** llama.cpp separates that into
   `reasoning_content`, so `content` stays clean — but the thinking still
   consumes the token budget. `LLM_MAX_TOKENS` needs headroom (~1200) or the
   answer truncates mid-JSON.
2. **It is slow (~6s/call).** Every call site must be bounded. See
   `LLM_MAX_ENTITY_ADJUDICATIONS`, and the 90-second screening budget in
   DEV_B B16.

Every mechanical QRC rule stays in `rules_engine` (MASTER §7) — nothing here
decides a designation, a business unit, or a cross-border outcome. If a call
fails or the server is down, the caller's `fallback` is returned and the
screening still completes.
"""

from __future__ import annotations

import json
import logging
from typing import TypeVar

from pydantic import BaseModel, ValidationError
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import settings

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

ANTI_FABRICATION = (
    "Never invent an entity, designation, partner name, date, or rule. "
    "If a field is absent from the input, say it was not found. "
    "Reply with JSON only. Keep every free-text field to one short sentence."
)

_client = None
_availability: bool | None = None


def _get_client():
    global _client
    if _client is None:
        from openai import OpenAI

        _client = OpenAI(
            base_url=settings.LLM_BASE_URL,
            api_key=settings.LLM_API_KEY,
            timeout=settings.LLM_TIMEOUT_SECONDS,
            max_retries=0,  # tenacity owns retries
        )
    return _client


def llm_available(refresh: bool = False) -> bool:
    """True when an inference server is reachable. Cached — a screening should
    not pay a probe per call."""
    global _availability
    if not settings.LLM_ENABLED:
        return False
    if _availability is not None and not refresh:
        return _availability
    try:
        _get_client().models.list()
        _availability = True
    except Exception as exc:  # noqa: BLE001 - unreachable server is a normal state
        log.warning("LLM unavailable at %s (%s) — judgment calls will use fallbacks", settings.LLM_BASE_URL, exc)
        _availability = False
    return _availability


def _inline_refs(node, defs: dict):
    """Replace every $ref with the definition it points at.

    llama.cpp builds a GBNF grammar from the schema and cannot resolve
    $ref/$defs, so nested models (a list of QCFlag, say) must be inlined or
    the request fails with 'Error resolving ref'.
    """
    if isinstance(node, list):
        return [_inline_refs(item, defs) for item in node]
    if not isinstance(node, dict):
        return node

    ref = node.get("$ref")
    if ref and ref.startswith("#/$defs/"):
        target = defs.get(ref.split("/")[-1], {})
        merged = {k: v for k, v in node.items() if k != "$ref"}
        return _inline_refs({**target, **merged}, defs)

    return {key: _inline_refs(value, defs) for key, value in node.items()}


def _tidy(node):
    """Strip annotations llama.cpp ignores, and require every property."""
    if isinstance(node, list):
        return [_tidy(item) for item in node]
    if not isinstance(node, dict):
        return node

    node = {k: _tidy(v) for k, v in node.items() if k not in ("title", "default")}
    if node.get("type") == "object" and "properties" in node:
        node["required"] = list(node["properties"].keys())
        node["additionalProperties"] = False
    return node


def _strict_schema(model: type[BaseModel]) -> dict:
    """Pydantic -> a JSON schema llama.cpp accepts in strict mode."""
    schema = model.model_json_schema()
    defs = schema.pop("$defs", {})
    return _tidy(_inline_refs(schema, defs))


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=6), reraise=True)
def _complete(schema_model: type[T], system_prompt: str, user_prompt: str) -> T:
    response = _get_client().chat.completions.create(
        model=settings.LLM_MODEL,
        temperature=settings.LLM_TEMPERATURE,
        max_tokens=settings.LLM_MAX_TOKENS,
        messages=[
            {"role": "system", "content": f"{system_prompt}\n\n{ANTI_FABRICATION}"},
            {"role": "user", "content": user_prompt},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": schema_model.__name__,
                "strict": True,
                "schema": _strict_schema(schema_model),
            },
        },
        # llama.cpp extensions: suppress the thinking budget so the token
        # allowance goes to the answer rather than the scratchpad.
        extra_body={"reasoning_budget": 0},
    )

    content = (response.choices[0].message.content or "").strip()
    if not content:
        raise ValueError("model returned no content (thinking may have consumed max_tokens)")
    return schema_model.model_validate(json.loads(content))


def ask_structured(schema_model: type[T], system_prompt: str, user_prompt: str, fallback: T) -> T:
    """Structured judgment call. Returns `fallback` when the server is
    unreachable or the call fails after retries — never raises into the
    graph (DEV_B B15)."""
    if not llm_available():
        return fallback
    try:
        return _complete(schema_model, system_prompt, user_prompt)
    except (ValidationError, json.JSONDecodeError) as exc:
        log.warning("LLM returned unparseable output for %s: %s", schema_model.__name__, exc)
        return fallback
    except Exception as exc:  # noqa: BLE001 - a failed judgment call must not fail the screening
        log.warning("LLM call failed after retries (%s): %s", schema_model.__name__, exc)
        return fallback
