"""Streaming variant of the agent loop.

`run_agent` blocks until the agent is finished, which for a screening question
is 40-120s of silence. This yields events as they happen instead:

    {"type": "status",    "message": "..."}          agent is thinking
    {"type": "tool_call", "tool": ..., "args": ...}  a tool is about to run
    {"type": "tool_result", "tool": ..., "summary": ...}
    {"type": "token",     "text": "..."}             answer, token by token
    {"type": "done",      "content": ..., "trace": ..., "citations": [...]}
    {"type": "error",     "message": "..."}

Same loop, same tools, same guarantees as `run_agent` — the difference is
only that the caller sees progress. Tool calls arrive from the model as
fragments across many chunks, so they are accumulated by index before being
executed.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterator

from app.agents import tools as tool_registry
from app.agents.llm import ANTI_FABRICATION, llm_available
from app.agents.runtime import AgentRun
from app.config import settings

log = logging.getLogger(__name__)


def _accumulate(store: dict[int, dict], deltas) -> None:
    """Merge streamed tool-call fragments into whole calls, keyed by index."""
    for delta in deltas:
        slot = store.setdefault(delta.index, {"id": "", "name": "", "arguments": ""})
        if delta.id:
            slot["id"] = delta.id
        if delta.function and delta.function.name:
            slot["name"] += delta.function.name
        if delta.function and delta.function.arguments:
            slot["arguments"] += delta.function.arguments


def _result_summary(name: str, result: dict) -> str:
    if not isinstance(result, dict):
        return "done"
    if "error" in result:
        return f"error: {str(result['error'])[:90]}"
    for key in ("total_matches", "total_engagements", "total_classified"):
        if key in result:
            return f"{result[key]} result(s)"
    for key in ("risk_tier", "business_unit", "outcome"):
        if key in result:
            return str(result[key])
    if "rules" in result:
        return f"{len(result['rules'])} rule chunk(s)"
    if "contradiction" in result:
        return "contradiction found" if result["contradiction"] else "no contradiction"
    if "relevant" in result:
        return "relevant" if result["relevant"] else "not relevant"
    if "acknowledged" in result:
        return "acknowledged" if result["acknowledged"] else "not acknowledged"
    return "done"


def stream_agent(
    agent_name: str,
    system_prompt: str,
    user_prompt: str,
    tool_names: list[str] | None,
    max_turns: int = 12,
) -> Iterator[dict]:
    run = AgentRun(agent=agent_name)
    started = time.time()

    if not llm_available():
        yield {
            "type": "error",
            "message": "The inference server is unreachable, so I cannot answer this. "
                       "Screening and the deterministic QRC rules still work — only chat needs the model.",
        }
        return

    from app.agents.llm import _get_client

    client = _get_client()
    specs = tool_registry.specs(tool_names)
    messages: list[dict] = [
        {"role": "system", "content": f"{system_prompt}\n\n{ANTI_FABRICATION}"},
        {"role": "user", "content": user_prompt},
    ]

    seen_calls: set[tuple[str, str]] = set()
    repeats = 0

    try:
        for turn in range(max_turns):
            run.turns += 1
            yield {"type": "status", "message": "Thinking…" if turn == 0 else "Working through the results…"}

            stream = client.chat.completions.create(
                model=settings.LLM_MODEL,
                temperature=settings.LLM_TEMPERATURE,
                max_tokens=settings.LLM_MAX_TOKENS,
                messages=messages,
                tools=specs or None,
                extra_body={"reasoning_budget": 0},
                stream=True,
            )

            content_parts: list[str] = []
            pending: dict[int, dict] = {}
            streamed_any = False

            for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta.tool_calls:
                    _accumulate(pending, delta.tool_calls)
                if delta.content:
                    content_parts.append(delta.content)
                    streamed_any = True
                    # Only emit tokens once we know this turn is the answer
                    # rather than a preamble to a tool call.
                    if not pending:
                        yield {"type": "token", "text": delta.content}

            content = "".join(content_parts).strip()

            if not pending:
                run.content = content
                if not streamed_any and content:
                    yield {"type": "token", "text": content}
                break

            # A turn that both narrated and called tools: the narration was
            # withheld above, so surface it as status rather than as answer.
            if content:
                yield {"type": "status", "message": content[:200]}

            calls = [pending[i] for i in sorted(pending)]
            messages.append({
                "role": "assistant",
                "content": content,
                "tool_calls": [
                    {
                        "id": c["id"] or f"call_{i}",
                        "type": "function",
                        "function": {"name": c["name"], "arguments": c["arguments"] or "{}"},
                    }
                    for i, c in enumerate(calls)
                ],
            })

            for i, call in enumerate(calls):
                name = call["name"]
                try:
                    args = json.loads(call["arguments"] or "{}")
                except json.JSONDecodeError:
                    args = {}

                signature = (name, json.dumps(args, sort_keys=True, default=str))
                if signature in seen_calls:
                    repeats += 1
                    messages.append({
                        "role": "tool",
                        "tool_call_id": call["id"] or f"call_{i}",
                        "content": json.dumps({
                            "note": f"You already called {name} with these arguments. "
                                    "Do not repeat it — move on or give your final answer.",
                        }),
                    })
                    continue
                seen_calls.add(signature)

                yield {"type": "tool_call", "tool": name, "args": args}
                result = tool_registry.execute(name, args)
                run.tool_calls.append({
                    "tool": name,
                    "args": args,
                    "result_count": result.get("total_matches", 0) if isinstance(result, dict) else 0,
                })
                run.results.append({"tool": name, "args": args, "result": result})
                yield {"type": "tool_result", "tool": name, "summary": _result_summary(name, result)}

                messages.append({
                    "role": "tool",
                    "tool_call_id": call["id"] or f"call_{i}",
                    "content": tool_registry.serialise(result),
                })

            if repeats >= 4:
                messages.append({
                    "role": "user",
                    "content": "Stop calling tools. Summarise what you found and finish.",
                })
                final = client.chat.completions.create(
                    model=settings.LLM_MODEL,
                    temperature=settings.LLM_TEMPERATURE,
                    max_tokens=settings.LLM_MAX_TOKENS,
                    messages=messages,
                    extra_body={"reasoning_budget": 0},
                    stream=True,
                )
                parts: list[str] = []
                for chunk in final:
                    if chunk.choices and chunk.choices[0].delta.content:
                        piece = chunk.choices[0].delta.content
                        parts.append(piece)
                        yield {"type": "token", "text": piece}
                run.content = "".join(parts).strip()
                break
        else:
            run.error = f"hit the {max_turns}-turn budget without finishing"
    except Exception as exc:
        log.exception("Streaming agent %s failed", agent_name)
        yield {"type": "error", "message": str(exc)}
        return

    run.seconds = time.time() - started
    log.info("[%s] streamed in %.1fs — %s", agent_name, run.seconds, run.summary())
    yield {"type": "done", "run": run}
