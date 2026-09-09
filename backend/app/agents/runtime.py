"""The agent loop.

An agent here is a system prompt plus a subset of the tool registry. It runs
a real OpenAI tool-calling loop: the model chooses a tool, we execute it, feed
the result back, and repeat until it stops calling tools or hits its turn
budget.

Every tool call in `AgentRun.tool_calls` is an invocation that actually
happened, with the arguments the model chose and a digest of what came back.
The trace panel renders that, not a reconstruction.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field

from app.agents import tools as tool_registry
from app.agents.llm import ANTI_FABRICATION, llm_available
from app.config import settings

log = logging.getLogger(__name__)


@dataclass
class AgentRun:
    agent: str
    content: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    results: list[dict] = field(default_factory=list)
    reasoning: list[str] = field(default_factory=list)
    turns: int = 0
    seconds: float = 0.0
    degraded: bool = False
    error: str | None = None

    def summary(self) -> str:
        if self.error:
            return f"failed: {self.error}"
        if self.degraded:
            return "LLM unavailable — agent skipped"
        tools = ", ".join(sorted({c["tool"] for c in self.tool_calls})) or "no tools"
        return f"{self.turns} turn(s), {len(self.tool_calls)} tool call(s): {tools}"

    def results_for(self, tool_name: str) -> list[dict]:
        return [r["result"] for r in self.results if r["tool"] == tool_name]


def run_agent(
    agent_name: str,
    system_prompt: str,
    user_prompt: str,
    tool_names: list[str] | None,
    max_turns: int = 12,
) -> AgentRun:
    """Drive one agent to completion. Never raises — a failed agent degrades
    to an empty run so the graph continues (DEV_B B15)."""
    run = AgentRun(agent=agent_name)
    started = time.time()

    if not llm_available():
        run.degraded = True
        run.seconds = time.time() - started
        return run

    from app.agents.llm import _get_client  # local import keeps client lazy

    client = _get_client()
    specs = tool_registry.specs(tool_names)
    messages: list[dict] = [
        {"role": "system", "content": f"{system_prompt}\n\n{ANTI_FABRICATION}"},
        {"role": "user", "content": user_prompt},
    ]

    seen_calls: dict[tuple[str, str], str] = {}
    repeats = 0

    try:
        for _ in range(max_turns):
            run.turns += 1
            if repeats >= 4:
                # The model is spinning rather than progressing. Ask once for
                # a final answer from what it already has.
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
                )
                run.content = (final.choices[0].message.content or "").strip()
                break
            response = client.chat.completions.create(
                model=settings.LLM_MODEL,
                temperature=settings.LLM_TEMPERATURE,
                max_tokens=settings.LLM_MAX_TOKENS,
                messages=messages,
                tools=specs or None,
                extra_body={"reasoning_budget": 0},
            )
            choice = response.choices[0]
            message = choice.message
            calls = message.tool_calls or []

            # Qwen-style reasoning models return their scratchpad separately.
            # It is not part of the answer, but it is what the agent was
            # actually weighing — worth surfacing when explaining a decision.
            thinking = getattr(message, "reasoning_content", None) or (
                (message.model_extra or {}).get("reasoning_content")
                if hasattr(message, "model_extra") else None
            )
            if thinking:
                run.reasoning.append(thinking.strip())

            if not calls:
                run.content = (message.content or "").strip()
                break

            messages.append({
                "role": "assistant",
                "content": message.content or "",
                "tool_calls": [
                    {
                        "id": c.id,
                        "type": "function",
                        "function": {"name": c.function.name, "arguments": c.function.arguments},
                    }
                    for c in calls
                ],
            })

            for call in calls:
                name = call.function.name
                try:
                    arguments = json.loads(call.function.arguments or "{}")
                except json.JSONDecodeError:
                    arguments = {}

                # Small models get stuck repeating one call. Serve the cached
                # result with a nudge instead of re-running the query, so the
                # loop can't silently eat the turn budget.
                signature = (name, json.dumps(arguments, sort_keys=True, default=str))
                if signature in seen_calls:
                    repeats += 1
                    messages.append({
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": json.dumps({
                            "note": f"You already called {name} with these arguments. "
                                    "Do not repeat it. Move on to the next entity or source, "
                                    "or give your final answer.",
                            "previous_result": seen_calls[signature],
                        })[:2000],
                    })
                    continue

                result = tool_registry.execute(name, arguments)
                seen_calls[signature] = tool_registry.serialise(result, limit=1200)
                run.tool_calls.append({
                    "tool": name,
                    "args": arguments,
                    "result_count": result.get("total_matches", len(result) if isinstance(result, dict) else 0),
                })
                run.results.append({"tool": name, "args": arguments, "result": result})
                log.info("[%s] %s(%s)", agent_name, name, arguments)

                messages.append({
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": tool_registry.serialise(result),
                })
        else:
            run.error = f"hit the {max_turns}-turn budget without finishing"
    except Exception as exc:
        log.exception("Agent %s failed", agent_name)
        run.error = str(exc)

    run.seconds = time.time() - started
    log.info("[%s] done in %.1fs — %s", agent_name, run.seconds, run.summary())
    return run


def finalize_structured(run: AgentRun, schema_model, instruction: str, fallback):
    """Convert an agent's free-text conclusion into a typed object.

    Tool calling and `response_format: json_schema` don't compose in one
    request, so the agent reasons with tools first and we extract afterwards
    from what it concluded. The extraction sees only the agent's own output —
    it cannot introduce facts the agent didn't reach.
    """
    from app.agents.llm import ask_structured

    if run.degraded or not run.content:
        return fallback
    return ask_structured(
        schema_model,
        system_prompt=instruction,
        user_prompt=f"Analyst agent's findings:\n\n{run.content}",
        fallback=fallback,
    )


def trace_entry(run: AgentRun) -> dict:
    return {
        "agent": run.agent,
        "summary": run.summary(),
        "tool_calls": run.tool_calls,
        "seconds": round(run.seconds, 1),
    }
