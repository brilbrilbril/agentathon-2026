# Conflict Screening Multi-Agent Assistant — backend

Non-technical overview: [`../OVERVIEW_FOR_BUSINESS.md`](../OVERVIEW_FOR_BUSINESS.md)
Recorded agent Q&A: [`../QA_TRANSCRIPT.md`](../QA_TRANSCRIPT.md)

## Setup

```bash
# from repo root
docker compose up -d

cd backend
python -m venv .venv && source .venv/Scripts/activate   # Windows Git Bash
pip install -r requirements.txt
cp .env.example .env

alembic upgrade head
python scripts/run_ingestion.py          # idempotent: truncate + reload all four sources
uvicorn app.main:app --reload --port 8000    # docs at /docs
pytest -q -m "not slow"

# with an inference server running (see below)
python -m app.eval.run_eval 12246557     # score against the analyst's answer key
python scripts/qa_smoke.py --md ../QA_TRANSCRIPT.md

cd ../frontend && npm install && npm run dev  # http://localhost:5173
```

Postgres runs on **port 5434** to avoid clashing with other local containers.

## Inference

Any OpenAI-compatible endpoint. Defaults target a local `llama.cpp` server:

```bash
LLM_BASE_URL=http://localhost:8080/v1
LLM_MODEL=Qwen3.5-4B
LLM_API_KEY=sk-no-key-required
```

Needs a server started with tool-calling support (`--jinja`). Verify:

```bash
curl -s http://localhost:8080/v1/models
curl -s http://localhost:8000/api/v1/health   # reports "llm": true|false
```

**Notes for small local models.** Qwen3.5 reasons before answering and llama.cpp returns
that separately as `reasoning_content`, so `content` stays clean. Two consequences are
baked into the config:

- `LLM_MAX_TOKENS=1200` — thinking consumes budget; less and JSON answers truncate.
- Structured output uses `response_format: json_schema`, with schemas **inlined**
  (`llm._strict_schema`) because llama.cpp cannot resolve `$ref`/`$defs`.

If the server is unreachable, agents degrade to empty runs and the screening still
completes rather than failing.

---

## Architecture

### The agent loop is real

`app/agents/runtime.py` runs an actual OpenAI tool-calling loop: the model picks a tool, we
execute it, feed the result back, repeat. Everything in `AgentRun.tool_calls` is an
invocation that genuinely happened with arguments the model chose — the UI trace panel
renders that, not a reconstruction.

Loop protection: an identical `(tool, args)` pair is served from cache with a nudge to move
on, and four repeats force a final answer. Small models otherwise spin.

### The four agents

| Agent | Tools it holds | Decides |
|---|---|---|
| **orchestrator** | `get_case_details`, `search_rules` | Quality checks (slides 3, 4); the search plan |
| **search** | the 5 entity-search tools | Which entities to search, where, whether to expand to a DESC-named GUP |
| **rules** | rule retrieval + every `rules_engine` tool | Which rules apply; contradictions; triage; cross-border |
| **synthesis** | `get_footer_text` | Conditions, final result, the draft response |

Graph wiring: `app/agents/graph.py`. Chat (`app/services/chat_agent.py`) is a single agent
holding almost the whole registry.

### The tool registry — `app/agents/tools.py`

**Entity search (5)** — `search_desc_entities`, `search_wbs_engagements`,
`search_cot_requests`, `search_dccs_history`, `search_one_window` *(stub; returns
`unchecked: true`)*

**Engagement-team search (2)** — `search_engagements_by_partner`,
`get_desc_responsible_party`. The entity searches answer *"is this client conflicted?"*;
these answer the people side — whether staffing a named partner creates an issue, and who
holds the DESC relationship. Both matter because `Audit Team Restricted` (slide 5) and
Personal Conflicts (slide 14) turn on who is staffed, not just who the client is.

**Rulebook (3)** — `get_rules_by_source`, `search_rules`, `get_footer_text`

**Deterministic verdicts (7)** — `classify_wbs_business_unit`, `classify_wbs_status`,
`is_cot_match_acknowledged`, `is_dccs_match_relevant`, `parse_desc_designations`,
`compare_stated_vs_desc_designation`, `evaluate_cross_border`

**Triage + disambiguation (2)** — `assess_risk_tier`, `adjudicate_same_entity`

**Bulk + case (2)** — `apply_qrc_rules_to_all_matches`, `get_case_details`

21 tools total. `search_engagements_by_partner` reports engagement records only — there is
no HR, directorship or personal-holdings data in this build, and the tool says so in its
own output so the agent passes the limitation on rather than implying a clean check.

Search tools return a compact digest (8 rows + counts) because the model has limited
context and the sources are large. The **full** match objects are captured in
`tools._collected`, so the persisted table is the output of tools the agent actually
called, not a second pipeline it never saw.

---

## Deterministic vs. model — the split that matters

MASTER §7: *"If an agent prompt asks the model to decide something in the [mechanical]
list, that is a bug."*

| | Mechanical | Judgement |
|---|---|---|
| Owner | `app/rules/rules_engine.py` | the model |
| Examples | WBS business unit & status (slide 6), COT cutoff (slide 9), DCCS staleness/status/dedupe (slide 10), cross-border matrix (slide 11), DESC-vs-request comparison (slide 4), risk tiering | which rules apply, whether a fuzzy hit is the same legal entity, whether the offering matches the engagement, how the response reads |
| Varies? | Never — same input, same verdict | Yes |

**The agent doesn't bypass this — it calls it.** `rules_engine` is exposed as tools, so the
model chooses *when* to apply a rule and gets back an unarguable verdict plus its slide
citation. Determinism lives inside tools; orchestration is agentic.

Two invariants are enforced in code rather than trusted to the prompt:

- **The slide-14 footer** is re-appended from `get_footer_text()` if the agent altered or
  omitted it (`synthesis_agent`) — it must be byte-identical (B11).
- **`NO_CONFLICTS_IDENTIFIED` is overridden** to `APPROVED_WITH_CONDITIONS` when the
  summary table is non-empty.

---

## Risk triage — turning a list into a worklist

The submission deck promises the agent *"routes only genuinely risk-relevant matches to
reviewers rather than surfacing an undifferentiated list of hits."* A screening finds ~160
includable matches, so that promise is the difference between useful and unusable.

`rules_engine.assess_risk_tier` tiers every included match from verdicts other QRC rules
already produced, so a tier is always explainable and never drifts:

| Tier | Meaning | Triggers |
|---|---|---|
| **High** | Independence risk — read first | Restricted designation (slide 5); Audit engagement (slide 6); DESC contradicting the request (slide 4) |
| **Medium** | A condition is likely | Relationship / Watchlist / Loan Rule (slide 5); Assurance engagement (slide 6); **anything unrecognised** |
| **Low** | Record only | Ongoing Non-Assurance work; prior DCCS activity (slide 10) |

On case 12246557 this takes **160 matches down to 2 needing attention** — the Restricted
GUP (High) and the Relationship entity (Medium).

The result screen splits on it: *"Needs your attention"* renders High and Medium; Low
collapses behind *"For the record"*. `summary_table` is sorted highest-risk-first and the
payload carries a `risk_summary` count per tier.

`adjudicate_same_entity` covers the deck's other pillar, disambiguation. It returns
**facts, not a verdict** — normalised names, country match, GUP — because whether two
records are the same legal entity is a judgement call (MASTER §7). The agent decides, and
weeds out false positives like `Motto Auction Thailand Company Limited` matching
`KDDI (Thailand) Limited` at 0.76.

`run_eval` includes `risk_triage_differentiates`, which fails if triage degenerates into
"everything is High" — the obvious way to fake this.

---

## Robustness to a different dataset

A new dataset with the same *structure* but different *words* — new designation labels, new
statuses, new service lines, renamed columns — must not silently produce a wrong answer.
The governing rule:

> **Unknown must escalate or surface. Never silently pass.**

| Risk | Before | Now |
|---|---|---|
| Designation not in the reference vocabulary | Fell through to **Low** — silent under-triage | **Medium**, "unrecognised … not risk-assessed, reviewer to confirm" |
| A new `"… Restricted"` label (e.g. Sanctions Restricted) | Not matched — treated as unrestricted | Matched on the marker word → **High** |
| WBS L4 label spaced/cased differently | Exact match → Audit silently downgraded to Non-Assurance | Matched on content (`aud` + `large` + `complex`) |
| Service line outside slide 6 | Presented as a rulebook verdict | Non-Assurance, citation reads "assumed — not covered by slide 6" |
| Unfamiliar business unit | Low risk | **Medium**, "could not be classified" |
| Renamed xlsx column | Field silently NULL | Matched case/space/punctuation-insensitively; unresolved ones logged |
| DCCS row with unfamiliar status wording | Row silently dropped | Status located by position (field before the date); unparseable rows counted and warned |
| No matching country | Location silently null | Logged, with a pointer to extend the list |

What deliberately stays hardcoded: the **rules themselves**. Slide 6's Audit test, slide 9's
cutoff, slide 10's staleness window, the slide 11 matrix — these come from the rulebook, not
the data. If the rulebook changes they change with it; that is what makes a verdict
auditable. What is now data-driven is everything that was really an assumption about *this*
export.

### Worked example

Re-ingesting the existing sample after these changes took DCCS history from **3,480 to
3,907 rows** — ~427 rows had been silently dropped because their status wording wasn't in
the vocabulary, and nothing reported it.

An intermediate version overshot: a "looks like a status" shape heuristic pulled Entity Name
and Request Type values into the status column, inventing ~1,400 junk rows
(`status = 'KDDI Corporation'`). Caught by checking the status *distribution* rather than
the row count, and removed. Position-anchoring is kept; shape-guessing is not, and
implausible values now record `status = NULL` instead of a lie — see `_find_status_idx`
and `_is_plausible_status`.

Covered by the "robustness to a different dataset" block in `tests/test_rules_engine.py`.

---

## Pipeline end to end

### Phase 0 — offline ingestion (`scripts/run_ingestion.py`)

Runs once, idempotently (truncate + reload). Nothing is parsed at request time.

```
Sample_3_3.xlsx ─┬─ DESC sheet ─► desc_entities      2 rows   (pg_trgm GIN, full row in JSONB)
                 ├─ WBS  sheet ─► wbs_engagements   14 rows
                 └─ COT  sheet ─► cot_requests       7 rows
                        ▲
                        └─ headers matched case/space/punctuation-insensitively;
                           unresolved columns logged, never silently NULL

Sample_3_1.pdf ──► pdftotext -layout -enc UTF-8 ──► section splitter
                 ├─► cases + case_parties            3 parties (Client / Shareholder / GUP)
                 ├─► dccs_search_results         3,907 rows  ← the 4th database
                 └─► golden_cases                    the analyst's recorded determination
                        ▲
                        └─ status located by vocabulary, else by position (field before
                           the date); unparseable rows counted and warned, not dropped

QRC .pptx ──────► python-pptx ──► semantic chunker ──► rule_chunks  19 chunks
                                                       (tsvector + GIN, dict by source_db)
```

The PDF is the awkward one: it renders each form field's *value* one slot above its own
caption, so the ordered right-column values reconstruct the field sequence positionally
rather than lining up with the label printed beside them. See the module docstring in
`app/ingestion/pdf_loader.py`.

### Phase 1 — screening (`app/agents/graph.py`)

Four agents, each a system prompt plus a slice of the tool registry, driven by a real
tool-calling loop. Times are from a Qwen3.5-4B run on case 12246557.

```
  ┌─ ORCHESTRATOR ───────────────────────────────────────────────── ~50s ─┐
  │ tools: get_case_details, search_rules                                 │
  │  • loads the case and its parties                                     │
  │  • QC slide 3: service offering vs engagement description             │
  │  • QC slide 3: inbound referral without an IWRF                       │
  │  • QC slide 4: relevant-party completeness  → INFO flag               │
  │  → emits the search plan                                              │
  └───────────────────────────────┬───────────────────────────────────────┘
                                  ▼
  ┌─ SEARCH ─────────────────────────────────────────────────────── ~70s ─┐
  │ tools: search_desc / wbs / cot / dccs_history / one_window            │
  │  • every party × all 5 sources; DESC first (it is authoritative)      │
  │  • one-level GUP expansion when DESC names a parent not on the request│
  │  • coverage check: any (entity, source) pair the agent skipped is fed │
  │    back as a gap list and it finishes the job                         │
  │  → 431 matches; 428 confident, 3 below threshold for review           │
  └───────────────────────────────┬───────────────────────────────────────┘
                                  ▼
  ┌─ RULES & COMPLIANCE ─────────────────────────────────────────── ~75s ─┐
  │ tools: apply_qrc_rules_to_all_matches, compare_stated_vs_desc_        │
  │        designation, evaluate_cross_border, assess_risk_tier,          │
  │        adjudicate_same_entity, get_rules_by_source, + slide lookups   │
  │  • bulk-classifies every match: slides 5, 6, 9, 10                    │
  │  • diffs each party's stated designation against DESC   → WARN flag   │
  │  • adjudicates borderline matches → false positives rejected          │
  │  • tiers every included match High / Medium / Low                     │
  │  • cross-border per foreign jurisdiction (slide 11)                   │
  │  → 160 included, 268 excluded each with a reason                      │
  └───────────────────────────────┬───────────────────────────────────────┘
                                  ▼
  ┌─ SYNTHESIS ──────────────────────────────────────────────────── ~45s ─┐
  │ tools: get_footer_text                                                │
  │  • conditions: derived from rule verdicts, agent's own merged on top  │
  │  • final result (NO_CONFLICTS only when the table is empty)           │
  │  • draft response, then the slide-14 footer appended VERBATIM         │
  └───────────────────────────────┬───────────────────────────────────────┘
                                  ▼
                    screenings + matches (with risk_tier)
```

Findings are read back from **the tool results**, not from re-parsing the agent's prose —
the agent chose the tool and the arguments, the tool returned the verdict.

Two invariants are enforced after the fact rather than trusted to the prompt: the footer is
re-appended if the agent altered it, and `NO_CONFLICTS_IDENTIFIED` is overridden when the
summary table is non-empty.

### Phase 2 — delivery

```
POST /api/v1/cases/{id}/screen    → 202 {screening_id}   BackgroundTasks, no Celery
GET  /api/v1/screenings/{id}      → poll every 2s while RUNNING; full payload on COMPLETE
POST /api/v1/chat                 → the chat agent + its trace and citations
POST /api/v1/cases/{id}/evaluate  → runs the pipeline, scores it against golden_cases
GET  /api/v1/search/entities      → direct fuzzy lookup across the four sources
GET  /api/v1/rules                → all 19 chunks, for the Guide tab
```

The result screen opens on the triaged worklist, renders the DESC-contradiction WARN
prominently, and keeps `possible_matches` / `excluded_matches` collapsible with reasons.

### Retrieval

Two-stage, with **no embeddings** (MASTER §3):

1. `pg_trgm` prefilter in Postgres, deliberately loose (`similarity_threshold = 0.3`)
2. `rapidfuzz` `token_set_ratio` rerank over normalised names — uppercased, legal-form
   suffixes stripped, punctuation collapsed, non-ASCII preserved (aliases include
   `KDDI株式会社`)

That is what bridges the request's `KDDI (Thailand) Limited` to DESC's
`KDDI (THAILAND) COMPANY LIMITED`. Matches at or above `MATCH_THRESHOLD_AUTO_INCLUDE`
(0.80) go to the summary; between that and `MATCH_THRESHOLD_REVIEW` (0.65) they go to
`possible_matches` for the agent to adjudicate — never silently dropped.

---

## Example prompts

**Screening** — `POST /api/v1/cases/{case_id}/screen`, then poll the screening id, or
`python -m app.eval.run_eval 12246557`.

**Chat** — `POST /api/v1/chat` with `{"message": "...", "case_id": null}`. The questions
below are what an analyst actually asks, not questions about the rulebook. A screening
question makes the agent *do the work*: it searches all four sources, triages what it finds,
and answers with conditions.

| Analyst asks | Tools the agent reaches for |
|---|---|
| "We've been asked to do an HR transformation project for KDDI (Thailand) Limited, requested from Malaysia. Any conflicts, and what conditions apply?" | all 5 searches + `evaluate_cross_border` + `is_dccs_match_relevant` + `get_desc_responsible_party` |
| "A partner wants to pitch tax advisory to KDDI Corporation. Anything blocking it?" | all 5 searches + `search_engagements_by_partner` |
| "We're considering a statutory audit for KDDI Corporation. Is that allowed?" | searches + `compare_stated_vs_desc_designation` |
| "Of everything that came back for KDDI Corporation, what actually needs my attention?" | searches + triage |
| "We want to staff Soon Bee Koh as engagement partner on a new KDDI job. Conflict?" | `search_engagements_by_partner`, `get_desc_responsible_party` |
| "KDDI Corporation is Audit Team Restricted. What does that mean for who we staff?" | `get_desc_responsible_party`, `search_rules` |
| "Search brought back 'Motto Auction Thailand Company Limited' for my client 'KDDI (Thailand) Limited'. Same company?" | `adjudicate_same_entity` / `search_desc_entities` |
| "I found a conflict check dated 15 March 2021, Approved with Conditions. Does it still count?" | `is_dccs_match_relevant` |
| "The requestor says Restricted, DESC says Relationship. Which do I go with?" | `compare_stated_vs_desc_designation` |
| "What hasn't this tool checked that I still need to do myself?" | `search_one_window`, `search_rules` |

`scripts/qa_smoke.py --md ../QA_TRANSCRIPT.md` runs all 18 and writes a transcript with the
agent's own reasoning, the arguments it chose, and what each tool returned.
Last run: **18/18 answered using at least one tool**. Screening questions take 40–120s and
6–9 tool calls; single-rule lookups 11–27s and one call.

### Streaming

A screening question takes 40-120s on a local model, so the blocking endpoint meant a long
blank wait. `POST /api/v1/chat/stream` returns server-sent events instead:

```
data: {"type":"session","session_id":"..."}
data: {"type":"status","message":"Thinking…"}
data: {"type":"tool_call","tool":"is_cot_match_acknowledged","args":{"submission_time":"2025-06-01"}}
data: {"type":"tool_result","tool":"is_cot_match_acknowledged","summary":"not acknowledged"}
data: {"type":"token","text":"**No"}
...
data: {"type":"done","reply":"...","agent_trace":[...],"citations":[...],"seconds":13.0}
```

`app/agents/streaming.py` mirrors `run_agent` — same tools, same loop, same loop-protection.
The only subtlety is that streamed tool calls arrive as fragments across many chunks, so
they are accumulated by index before execution, and content is withheld from the token
stream until it's clear the turn is the answer rather than a preamble to a tool call.

The blocking `POST /api/v1/chat` still exists and leaves identical chat history.

The UI renders the tool calls live as they run, then the answer token by token, with a
Stop button wired to an `AbortController`. Answers are markdown (tables, headings, bold) —
`components/Markdown.tsx` renders them, and the draft response on the screening screen uses
the same component.

`GET /api/v1/chat/suggestions` returns the starter questions the chat screen shows as
clickable chips, grouped by category.

### Conversation history

Three separate things, and originally only the first worked:

| | |
|---|---|
| Turns written to `chat_sessions` / `chat_messages` | always did |
| `GET /api/v1/chat/{session_id}/messages` returns them | always did |
| **The agent sees prior turns** | added — `_history_context` |
| **The UI restores the conversation on refresh** | added — session id in `localStorage` |

Rows were being written and nothing read them back, so every question was answered in
isolation and a refresh looked like the history had been lost. Now a follow-up works:

> **Analyst:** Is KDDI Corporation listed in DESC?
> **Assistant:** Yes — KDDI CORPORATION, Japan, Audit Team Restricted, Relationship.
> **Analyst:** *And what designation does it carry?*
> **Assistant:** Audit Team Restricted, Relationship. *(resolved "it" from history, then
> re-ran `search_desc_entities` rather than trusting the earlier answer)*

The last 6 turns are included, assistant answers truncated to 700 characters — a full
screening answer is ~2,000 characters and the model's context is small, so replaying
several verbatim would crowd out the tool definitions. The prompt tells it to use history
only to resolve *what is being referred to*, and to re-run tools for any fact.

The chat screen shows the session id and a **New conversation** button; the id is keyed per
case in `localStorage`, so a case-scoped chat and the global one don't share a thread.

### Queries are case-insensitive

Entity search, partner search and every rule tool normalise their input, so casing,
padding and partial names all resolve the same way:

| Input | DESC | WBS |
|---|---|---|
| `KDDI CORPORATION` | 1 | 14 |
| `kddi corporation` | 1 | 14 |
| `Kddi Corporation` | 1 | 14 |
| `kddi corp` | 1 | 14 |
| `"  KDDI   Corporation  "` | 1 | 14 |

Same for `assess_risk_tier("audit team restricted")` → High and
`search_engagements_by_partner("soon bee koh")` → 9. Covered by the parametrised tests in
`tests/test_tools.py`.

### Two bugs the Q&A runs caught

Both were found by reading the transcript, not by a failing test:

1. **A vague date silently skipped a rule.** Asked about a 2021 DCCS match, the model passed
   `"2021"`, `safe_date` returned `None`, and the staleness test was skipped — producing a
   confident *"yes, include it"*. Rule tools now reject an unparseable date instead of
   half-applying the rule.
2. **`get_case_details` got an entity name.** The model reaches for it when it wants a
   company lookup; Postgres then raised on the UUID cast and the raw traceback went back to
   the model. It now returns a plain message pointing at the search tools.

---

## Verified against case 12246557

`python -m app.eval.run_eval 12246557` scores the pipeline against the analyst's stored
determination: final result, the DESC Relationship condition, WBS Non-Assurance (the
canary), WBS and COT matches, Japan cross-border, risk triage, and the DESC contradiction
WARN. Eight checks.

The **canary**: `KDDI - BCC ACCOUNTING ADVISORY` is filed under `Audit & Assurance` but its
L4 is `A&A: ASV-Accounting & Reporting`, not `AUD-Large & Complex`. Slide 6 therefore makes
it **Non-Assurance** — the analyst wrote `Local WBS: Non-Assurance`. If this ever returns
Audit, the classifier is broken.

---

## Reliability of the agentic pipeline

Making the pipeline genuinely agentic cost reliability, and getting it back took two fixes.
Both are the failure modes of a small model driving tools.

| Run | Score | What happened |
|---|---|---|
| Pre-agentic (scripted) | 7/7 | Deterministic pipeline; no real tool calls |
| First agentic run | **2/7** | The search agent read the orchestrator's "individual controlling the GUP is missing" flag and spent its whole budget hunting for a person (`KDDI CEO`, `Chairman of KDDI`). It never searched WBS, COT or DCCS. 1 match collected. |
| + coverage check | **5/7** | `search_agent._missing_coverage` compares tool calls made against `entities x 5 sources` and re-prompts with the gap list. 300 matches. |
| + harvest from tool results | **7/7** | The rules agent made the right calls but the prose-to-JSON extraction emitted malformed JSON and dropped them. Findings now come from the tool results themselves. |

Two design lessons are baked in:

- **Supervise coverage, don't script it.** The agent still decides how to search; it just
  doesn't get to leave a source unsearched.
- **Read verdicts from tool results, not the agent's prose.** The agent chose the tool and
  the arguments; the tool returned the verdict. Re-asking the model to summarise its own
  findings into JSON added a failure mode for no benefit.

---

## Known deviations and limits

- **Runtime is minutes, not the 90s in DEV_B B16.** A real tool loop on a 4B model costs
  5–40s per agent turn. The deterministic rules are instant; the time is inference.
- **Search and rules run sequentially, not in parallel** (B2 asks for a fan-out). The rules
  agent classifies what search retrieved, so it cannot start first. Four nodes (B1) and
  correct ordering were preferred.
- **Agent output varies between runs.** Which entities the search agent explores, and how
  many summary rows result, is model-dependent. Mechanical verdicts do not vary. Re-run
  `run_eval` after any prompt change.
- **Cross-border may raise jurisdictions beyond Japan** (Thailand, Singapore) because those
  parties are foreign to the requesting firm. The human analyst raised only Japan. The eval
  asserts Japan only; treat the others as candidates to confirm.
- **One Window is a stub** — no data provided; surfaced in `unchecked_sources`.
- **~26 DCCS rows carry merged-column text** (`'... ConfereApproved with Conditions'`) where
  the source PDF ran two columns together. Cosmetic; the source text is truncated there.
