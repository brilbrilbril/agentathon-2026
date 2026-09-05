# DEV B — Multi-Agent System (LangGraph) & Eval Harness

**Owner:** Dev B
**Scope:** All agents, tools, prompts, graph wiring, the `ScreeningService` Dev C calls, and the evaluation harness that scores output against the analyst's real answer.
**You do NOT touch:** SQL/ingestion internals (Dev A), FastAPI routes or React (Dev C).

**Read `MASTER_overview.md` and `00_SETUP_AND_REQUIREMENTS.md` first.**

> **Revision note.** Two changes from the earlier draft: (1) **DCCS Search Results is now a real data source**, not a stub — only One Window remains stubbed; (2) you own a new **eval harness** that scores the pipeline against ground truth from a closed case. That harness is the highest-value deliverable in the project after the core graph.

---

## Requirements — Dev B only

**Packages you own:**
```txt
langgraph>=0.2.50,<1.0
langchain-core>=0.3.20,<1.0
langchain-anthropic>=0.3,<1.0    # or langchain-openai
tenacity>=9.0,<10.0
pydantic>=2.9,<3.0
```

**Do not install** any embedding or vector library. Retrieval is Dev A's Postgres functions. See `MASTER` §3.

**Env vars:** `LLM_PROVIDER`, `LLM_MODEL`, `LLM_TEMPERATURE` (must be 0), `LLM_MAX_TOKENS`, `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`, `GRAPH_RECURSION_LIMIT`, `MATCH_THRESHOLD_AUTO_INCLUDE`, `MATCH_THRESHOLD_REVIEW`.

**Verify your API key works in the first 15 minutes.** A rate-limited or unfunded key discovered on Day 2 afternoon ends the project.

| # | Functional requirement |
|---|---|
| B1 | Exactly four agent nodes — orchestrator, search, rules, synthesis. Do not add more |
| B2 | Search and rules run in parallel; accumulator fields use `Annotated[list, operator.add]` |
| B3 | No agent re-derives a mechanical rule — all delegated to `rules_engine` |
| B4 | Every classified match carries a `rule_citation` naming the QRC slide |
| B5 | All LLM output uses `.with_structured_output()` against a Pydantic model |
| B6 | `temperature=0`; `recursion_limit` from config |
| B7 | DESC overrides the request; designation mismatch emits a WARN flag with the escalation path |
| B8 | GUP expansion is exactly one level — no recursion |
| B9 | Matches between review and auto-include thresholds go to `possible_matches`, never silently dropped |
| B10 | One Window is the only stub; it surfaces in `unchecked_sources` |
| B11 | The slide-14 footer is string-concatenated verbatim, never LLM-generated |
| B12 | Every excluded match records a human-readable `exclusion_reason` |
| B13 | Every agent prompt contains the anti-fabrication clause (§6) |
| B14 | Each chat turn persists to `chat_messages` with `agent_name` and `tool_calls` |
| B15 | `tenacity` retry (3 attempts, exponential backoff) wraps every LLM call; failure sets status `FAILED` with a message rather than raising |
| B16 | Screening completes in under 90 seconds |
| B17 | `run_eval(case_id)` scores output against `golden_cases` and prints a pass/fail table |

---

## 0. Interfaces

**From Dev A** (`app.repositories`, `app.rules`):
```python
search_desc(name, threshold, limit)         -> list[EntityMatch]
search_wbs(name, threshold, limit)          -> list[EntityMatch]
search_cot(name, threshold, limit)          -> list[EntityMatch]
search_dccs_history(name, threshold, limit) -> list[EntityMatch]
search_all(name)                            -> dict[MatchSource, list[EntityMatch]]
get_rules_by_source(source_db)              -> list[RuleChunk]     # PRIMARY
search_rules(query, source_db, top_k)       -> list[RuleChunk]     # FTS fallback
get_cross_border_table()                    -> RuleChunk
get_footer_text()                           -> str
golden_repository.get(case_id)              -> GoldenCase

# rules_engine — DETERMINISTIC, never reason about these yourself
classify_wbs_business_unit(l1, l4, wbs_text)
classify_wbs_status(status, complete_date, desc_designation)
is_cot_match_acknowledged(submission_time)
parse_desc_designations(designation_type)
is_dccs_match_relevant(request_date, status, already_in_other_source)
evaluate_cross_border(client_in_desc, gup_in_desc, client_is_gup)
compare_stated_vs_desc_designation(stated, desc_designation)
```

**To Dev C** (`app/services/screening_service.py`):
```python
async def run_screening(case_id: UUID) -> UUID
async def chat(session_id: UUID, case_id: UUID | None, message: str) -> ChatTurnResult
async def evaluate(case_id: UUID) -> EvalResult
```

---

## 1. Design principle — read before writing any agent

The QRC contains two kinds of instruction:

**Mechanical rules → deterministic Python.** WBS business-unit and status classification (slide 6), COT cutoff (slide 9), DCCS staleness and status tests (slide 10), cross-border matrix (slide 11), DESC-vs-request comparison (slide 4). Already implemented by Dev A. **Call them.**

**Judgment calls → LLM.** Service offering vs engagement details consistency, relevant-party completeness, whether a fuzzy hit is the same legal entity, and how the draft response reads.

If an agent prompt asks the model to decide something in the first list, that is a bug. This split is what makes the output auditable, and it is why the eval harness can pass.

---

## 2. The graph

```
                             ScreeningState
                                   │
                    ┌──────────────▼──────────────┐
                    │      ORCHESTRATOR AGENT     │
                    └──────┬───────────────┬──────┘
                           │ parallel fan-out
          ┌────────────────▼───┐      ┌────▼─────────────────────┐
          │   SEARCH AGENT     │      │  RULES & COMPLIANCE      │
          └────────────────┬───┘      └────┬─────────────────────┘
                           └───────┬───────┘
                    ┌──────────────▼──────────────┐
                    │     SYNTHESIS AGENT         │
                    └──────────────┬──────────────┘
                                   ▼
                        screenings + matches
```

```python
class ScreeningState(TypedDict):
    case_id: UUID
    request_id: str | None
    service_offering: str | None
    engagement_details: str | None
    location: str | None
    is_inbound_referral: bool
    has_iwrf: bool
    parties: list[Party]                       # name, entity_role, location, stated_designation, is_gup
    quality_check_flags: Annotated[list, operator.add]
    raw_matches: Annotated[list, operator.add]
    applicable_rules: Annotated[list, operator.add]
    classified_matches: list[ClassifiedMatch]
    possible_matches: list[EntityMatch]
    cross_border: CrossBorderDecision | None
    unchecked_sources: list[dict]
    conditions: list[str]
    final_result: str | None
    draft_response: str | None
    messages: Annotated[list, add_messages]
```

Use `langgraph.graph.StateGraph`. Fan-out is two edges from the orchestrator; LangGraph merges when both feed synthesis.

---

## 3. Agent specifications

### 3.1 Orchestrator

**Job:** turn a case into a search plan and run the QRC's quality checks.

1. Parties come from `case_parties` with roles already stated (`Client`, `Shareholder`, `Global Ultimate Parent`). **Do not LLM-extract them** — the ingested PDF gives them explicitly. LLM extraction is the fallback only for manually-entered cases with free-text party lists.
2. **QC — engagement details (slide 3).** Flag if the service offering contradicts the engagement description (e.g. offering is T&T but the description is an audit engagement), or if a client entity is named with no scope of services. `QCFlag(severity="WARN", action="Re-confirm with requestor")`. Never block.
3. **Referral check (slide 3).** If `is_inbound_referral` and not `has_iwrf` → flag: confirm with the ET/Governance team whether this is a local entity check only.
4. **Relevant-party completeness (slide 4).** Verify coverage of client, controlling shareholder, GUP, and the individual controlling the GUP — plus the same on the other side. Flag gaps as `INFO`.
5. Emit the plan: all party names, plus any DESC-derived GUP discovered later.

*On the sample case:* steps 2 and 3 produce nothing; step 4 produces one `INFO` flag because the individual controlling the GUP is not listed.

**Tools:** none. Pure LLM plus state. Keep it fast.

### 3.2 Search agent

**Job:** find every candidate. Retrieval only — no classification.

Tools:
```python
@tool search_desc_entities(entity_name: str)
@tool search_wbs_engagements(entity_name: str)
@tool search_cot_requests(entity_name: str)
@tool search_dccs_history(entity_name: str)      # REAL — thousands of rows from the PDF
@tool search_one_window(entity_name: str)        # STUB — returns [] + a note
```

Behaviour:
- Run all tools for every party name.
- **DESC is authoritative (slide 4).** After each DESC hit, call `compare_stated_vs_desc_designation(party.stated_designation, desc.designation_type)`. On the sample case this fires: the request claims `Restricted`, DESC says `Audit Team Restricted, Relationship`.
- Also diff `desc.gup_name` against the party list. If DESC names a GUP not present, add it and re-run searches **one level only**.
- Flag affiliates: a hit sharing a GUP with a Restricted entity but carrying no Restricted designation is a known DESC inconsistency (slide 4).
- Sub-threshold hits between `MATCH_THRESHOLD_REVIEW` and `MATCH_THRESHOLD_AUTO_INCLUDE` go to `possible_matches`. In compliance tooling a false negative is far worse than a false positive.
- `search_one_window` returns `[]` plus `{"source": "ONE_WINDOW", "reason": "..."}` appended to `unchecked_sources`.

### 3.3 Rules & compliance agent

**Job:** attach the governing rule to each raw match and classify it.

Per match:
1. `get_rules_by_source(match.source)` — deterministic lookup, not search.
2. Apply the deterministic classifier:
   - **WBS** → `classify_wbs_business_unit()` + `classify_wbs_status()`
   - **COT** → `is_cot_match_acknowledged()`; included rows forced `NON_ASSURANCE` + `ONGOING` (slide 9)
   - **DESC** → `parse_desc_designations()`; non-designated matches excluded from the summary but generating a Conditions caveat
   - **DCCS history** → `is_dccs_match_relevant()`, passing `already_in_other_source` computed by checking whether the same entity+partner already appears in a WBS or COT match (slide 10's dedupe test)
3. Attach `rule_citation`.
4. **LLM only for the residual judgment:** is this fuzzy hit the same legal entity? Prompt with both records side by side; expect `{same_entity: bool, confidence: float, reasoning: str}`.
5. Cross-border: derive `client_in_desc`, `gup_in_desc`, `client_is_gup` from DESC results and call `evaluate_cross_border()`.

DCCS history is the highest-volume source — thousands of rows before filtering. **Filter deterministically before any LLM call touches them**, or you will blow both the time budget and the token budget. The LLM should only see rows that survived slide 10's tests.

### 3.4 Synthesis agent

**Job:** produce the analyst-facing deliverable per slide 13.

**(a) Table summary** — one row per included match:
| Entity | Source | Country | Designation / Business unit | Partner / LCSP | Status | Rule cited |

**(b) Conditions** — derived from what was found: Restricted or Relationship designation in DESC, audit matches in WBS, the slide-5 caveat for non-designated matches, and a note for stubbed sources.

**(c) Final result** — `NO_CONFLICTS_IDENTIFIED` only when the summary is empty and there are no conditions; otherwise `APPROVED_WITH_CONDITIONS`.

**(d) Cross-border actions** — from `evaluate_cross_border()`.

**(e) Draft response** — composed narrative. **Always append the slide-14 footer verbatim** via `get_footer_text()` (DPM 1420 marketplace business relationship, then Personal Conflicts). String-concatenate it. The QRC states it applies to all SEA T&T cases.

**(f) Excluded matches appendix** — every dropped match with its reason. This is what makes the tool auditable and is the detail that will separate your demo.

---

## 4. Eval harness — `app/eval/run_eval.py`

Case 12246557 is a closed case with the analyst's real determination stored in `golden_cases`:
```
Final Result : Approved with Conditions
Conditions   : Relationship client in DESC
Comments     : Listed in DESC / Local WBS: Non-Assurance / WBS & COT match
Cross Border : Japan → Request Not Required ("Listed in DESC")
```

```python
async def evaluate(case_id: UUID) -> EvalResult:
    screening = await run_screening(case_id)
    golden = golden_repository.get(case_id)
    return score(screening, golden)
```

Scoring checks — keep them simple and string-tolerant, not exact-match:

| Check | Pass condition |
|---|---|
| `final_result` | pipeline result is `APPROVED_WITH_CONDITIONS` |
| `condition_desc_relationship` | some condition mentions a DESC `Relationship` designation |
| `wbs_non_assurance` | every included WBS match is `Non-Assurance` |
| `cot_match_found` | at least one COT match included |
| `wbs_match_found` | at least one WBS match included |
| `cross_border_japan` | Japan action is "not required", justified by the GUP being in DESC |
| `desc_contradiction_caught` | a WARN flag exists about the stated-vs-DESC designation mismatch |

Output a plain table: check name, expected, actual, pass/fail, and an overall score. Expose it through `GET /eval/{case_id}` for Dev C.

**Be honest in the demo:** this is one worked case, not a test set. It proves reproduction, not generalisation. Say so — it is a stronger position than overclaiming.

---

## 5. Chat mode

Same graph, different entry:
- Question references a case → answer from `classified_matches` already in the DB. Do not re-run screening.
- Procedural question ("when do I send a cross-border check?") → route to the rules agent, use `search_rules()` FTS, answer with a slide citation.
- Question names an entity with no case → run the search agent only.

Persist every turn to `chat_messages` with `agent_name` and `tool_calls`. Dev C renders the agent-trace panel from this, which carries most of the demo's visual impact.

---

## 6. Model and prompt notes

- One model throughout. `claude-sonnet-4-5` or an equivalent mid-tier model is plenty — the hard logic is deterministic. Config via `LLM_MODEL`.
- Structured output everywhere via `.with_structured_output()`. No regex over LLM prose.
- Every agent prompt includes: *"Never invent an entity, designation, partner name, date, or rule. If a field is absent from the tool result, output null and say it was not found. Cite the QRC slide number for every classification."*
- `temperature=0`, `recursion_limit=25`.
- Never pass raw DCCS history dumps into a prompt. Filter first, then summarise.

---

## 7. Deliverables checklist

- [ ] Graph compiles and runs end-to-end on case 12246557
- [ ] Orchestrator emits the relevant-party `INFO` flag
- [ ] Search agent finds hits in DESC, WBS, COT, and DCCS history
- [ ] **DESC contradiction caught** — request says `Restricted`, DESC says `Audit Team Restricted, Relationship` → WARN flag with the SEAIndependence escalation path
- [ ] **WBS canary** — `KDDI - BCC ACCOUNTING ADVISORY` (L4 `A&A: ASV-Accounting & Reporting`) classifies **Non-Assurance**. The analyst's answer key says `Local WBS: Non-Assurance`. If you output Audit, slide-6 logic is wrong
- [ ] DCCS history rows filtered deterministically before any LLM sees them; stale and `Opportunity Lost` rows excluded with reasons
- [ ] Cross-border Japan resolves to "not required" because the GUP is in DESC
- [ ] Draft response ends with the verbatim slide-14 footer
- [ ] `run_eval 12246557` prints a pass/fail table
- [ ] **Publish `run_screening()`, `chat()`, `evaluate()` signatures to Dev C by Day 1 midday** — ship them returning hardcoded fixtures immediately so Dev C is never blocked
