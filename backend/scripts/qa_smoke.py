"""Q&A harness — drives the chat agent through representative analyst questions
and writes a transcript: the question, the answer, every tool it called with the
real arguments and results, and the model's own reasoning.

Usage:
    python scripts/qa_smoke.py                      # console summary
    python scripts/qa_smoke.py --md ../QA_TRANSCRIPT.md

Needs a live inference server. Answers are model output, so this reports rather
than asserts — the assertions live in tests/test_tools.py.
"""

import argparse
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents import tools as tool_registry
from app.agents.runtime import run_agent
from app.config import settings
from app.services.chat_agent import CHAT_TOOLS, SYSTEM_PROMPT

logging.basicConfig(level="WARNING")

# What an analyst actually asks — "can we take this on?", not "what does slide 6
# say?". A screening question makes the agent do the work: search every source,
# triage what it finds, and answer with conditions.
QUESTIONS = [
    ("Screening", (
        "We've been asked to do an HR transformation project for KDDI (Thailand) "
        "Limited, requested from Malaysia. Are there any conflicts, and what "
        "conditions would apply?"
    )),
    ("Screening", (
        "A partner wants to pitch new tax advisory work to KDDI Corporation. "
        "Is there anything that would block it?"
    )),
    ("Screening", (
        "We're considering taking on a statutory audit for KDDI Corporation. "
        "Is that allowed?"
    )),
    ("Screening", (
        "Client is KDDI Asia Pacific Pte Ltd. What existing Deloitte relationships "
        "should I know about before we accept the engagement?"
    )),
    ("Screening", (
        "Of everything that came back for KDDI Corporation, what actually needs "
        "my attention?"
    )),

    # The people side, not the client side
    ("Engagement team", (
        "We want to staff Soon Bee Koh as engagement partner on a new KDDI "
        "job. Does that create a conflict?"
    )),
    ("Engagement team", (
        "KDDI Corporation is Audit Team Restricted. What does that mean for "
        "who we can put on this engagement?"
    )),
    ("Engagement team", (
        "Who do I need to clear this relationship with before we proceed on "
        "KDDI Corporation?"
    )),
    ("Engagement team", "Which Deloitte partners already serve KDDI Corporation, and where?"),

    ("Cross-border", (
        "Our client's ultimate parent is in Japan. Do I need to send a request "
        "to the Japan member firm before we start?"
    )),

    ("Disambiguation", (
        "Search brought back 'Motto Auction Thailand Company Limited' for my "
        "client 'KDDI (Thailand) Limited'. Is that actually the same company?"
    )),
    ("Disambiguation", (
        "Is 'KDDI (THAILAND) COMPANY LIMITED' the same client as "
        "'KDDI (Thailand) Limited'? Both are in Thailand under GUP KDDI CORPORATION."
    )),

    ("Rule application", (
        "I found a conflict check for this client dated 15 March 2021, "
        "status Approved with Conditions. Does it still count?"
    )),
    ("Rule application", (
        "The requestor says this entity is Restricted, but DESC says "
        "Relationship. Which do I go with?"
    )),
    ("Rule application", (
        "This engagement is filed under Audit & Assurance with Market "
        "Offering L4 'A&A: ASV-Accounting & Reporting', described as "
        "'KDDI - BCC ACCOUNTING ADVISORY'. Does that make them an audit client?"
    )),
    ("Rule application", (
        "An entity came back with a DESC designation of 'Sanctions "
        "Restricted', which I haven't seen before. How should I treat it?"
    )),

    ("Procedural", "When do I need to send a cross-border check to another member firm?"),
    ("Scope", "What hasn't this tool checked that I still need to do myself?"),
]


def ask(category: str, question: str) -> dict:
    """Run one question through the same agent the /chat endpoint uses, keeping
    the AgentRun so the transcript can show reasoning and tool results."""
    tool_registry.reset_collected()
    started = time.time()
    run = run_agent("conflict_assistant", SYSTEM_PROMPT, f"Question: {question}", CHAT_TOOLS, max_turns=12)
    return {
        "category": category,
        "question": question,
        "run": run,
        "seconds": time.time() - started,
    }


def _fmt_result(result: dict, limit: int = 900) -> str:
    text = json.dumps(result, indent=2, default=str, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + "\n  ... (truncated)"


def _args_inline(args: dict) -> str:
    parts = [f"{k}={v!r}" for k, v in args.items() if v not in (None, "", False)]
    joined = ", ".join(parts)
    return joined if len(joined) <= 110 else joined[:110] + "..."


def to_markdown(records: list[dict]) -> str:
    """Answer first, evidence folded away.

    An earlier version inlined every tool result, which made 57% of the file raw
    JSON and buried the later questions under a thousand lines of it — one
    question ran to 1,070 lines. The summary table keeps every question visible
    at a glance and the <details> blocks keep the evidence one click away.
    """
    used_tools = sum(1 for r in records if r["run"].tool_calls)
    lines = [
        "# Agent Q&A Transcript",
        "",
        (
            f"Generated {datetime.now().strftime('%Y-%m-%d %H:%M')} · "
            f"model `{settings.LLM_MODEL}` via `{settings.LLM_BASE_URL}`"
        ),
        "",
        (
            "Every answer below was produced by the chat agent calling **real tools**. Tool "
            "results and the model's own reasoning are folded away — expand a row to see "
            "exactly what came back."
        ),
        "",
        (
            "Mechanical verdicts (staleness, cutoffs, business-unit classification, "
            "cross-border, risk tiering) come from `rules_engine` behind those tools — the "
            "model decides *which* rule to apply, never *what the rule says*."
        ),
        "",
        f"**{used_tools}/{len(records)} questions answered using at least one tool.**",
        "",
        "---",
        "",
        "## All questions",
        "",
        "| # | Category | Question | Tools | Time |",
        "|---|---|---|---|---|",
    ]

    for i, record in enumerate(records, 1):
        run = record["run"]
        names = sorted({c["tool"] for c in run.tool_calls})
        cell = f"{len(run.tool_calls)} calls: " + ", ".join(f"`{n}`" for n in names[:3])
        if len(names) > 3:
            cell += f" +{len(names) - 3} more"
        question = record["question"].replace("|", "\\|")
        lines.append(
            f"| [{i}](#q{i}) | {record['category']} | {question} | {cell} | {record['seconds']:.0f}s |"
        )

    lines += ["", "---", ""]

    for i, record in enumerate(records, 1):
        run = record["run"]
        lines += [
            f'<a id="q{i}"></a>',
            "",
            f"## Q{i}. {record['question']}",
            "",
            (
                f"*{record['category']}* · `{record['seconds']:.0f}s` · "
                f"`{run.turns} turn(s)` · `{len(run.tool_calls)} tool call(s)`"
            ),
            "",
            "### Answer",
            "",
            run.content or "_(no answer produced)_",
            "",
            "### How it got there",
            "",
        ]

        if run.tool_calls:
            lines += [
                "Tools called, in order: " + ", ".join(f"`{c['tool']}`" for c in run.tool_calls),
                "",
            ]
            for call, result in zip(run.tool_calls, run.results):
                lines += [
                    "<details>",
                    f"<summary><code>{call['tool']}({_args_inline(call['args'])})</code></summary>",
                    "",
                    "```json",
                    _fmt_result(result["result"]),
                    "```",
                    "",
                    "</details>",
                    "",
                ]
        else:
            lines += ["_No tools called — answered directly._", ""]

        if run.reasoning:
            lines += ["<details>", "<summary>Agent reasoning</summary>", ""]
            for step, thought in enumerate(run.reasoning, 1):
                quoted = thought.replace("\n\n", "\n").replace("\n", "\n> ")
                lines += [f"**Step {step}.**", "", "> " + quoted, ""]
            lines += ["</details>", ""]

        lines += ["---", ""]

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--md", help="write a full markdown transcript to this path")
    args = parser.parse_args()

    records = []
    for i, (category, question) in enumerate(QUESTIONS, 1):
        print(f"[{i}/{len(QUESTIONS)}] {category}: {question}", flush=True)
        record = ask(category, question)
        run = record["run"]
        names = sorted({c["tool"] for c in run.tool_calls})
        print(f"    {record['seconds']:.0f}s · tools: {names or 'NONE'}", flush=True)
        records.append(record)

    used = sum(1 for r in records if r["run"].tool_calls)
    print(f"\n{used}/{len(records)} questions answered using at least one tool")

    if args.md:
        path = Path(args.md)
        if not path.is_absolute():
            path = (Path(__file__).resolve().parents[1] / path).resolve()
        path.write_text(to_markdown(records), encoding="utf-8")
        print(f"transcript written to {path}")


if __name__ == "__main__":
    main()
