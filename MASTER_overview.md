# MASTER — Conflict Screening Multi-Agent Assistant

**Read this first. Every coding agent working on any part of this repo should have this file in context.**

Reading order: `MASTER` → `00_SETUP_AND_REQUIREMENTS` → your own `DEV_A` / `DEV_B` / `DEV_C` file.

> **Revision note.** This supersedes an earlier draft. Two things changed:
> 1. **No embeddings, no vector database.** See §3. Nothing in this system is a semantic-similarity problem.
> 2. **The PDF is ingested knowledge, not a user upload.** See §2. There is no file-upload feature.

---

## 1. What this system is

A conflict-of-interest screening assistant for Deloitte SEA Tax & Transformation (T&T) analysts.

Today an analyst receives a conflict-check request in DCCS and manually searches several databases, applies a written rulebook to interpret each hit, then hand-writes a response. It is slow, repetitive, and inconsistent between analysts.

This system automates the search-and-classify pass and drafts the response, while keeping the analyst as the decision-maker. **It is a drafting aid, not an approval engine.** Every conclusion must cite the rule it came from so a human can check it.

---

## 2. The three source files and what each one IS

This is the single most important distinction in the project. Getting it wrong produces a system that looks smart and is wrong.

### 2.1 `Quick_Reference_Card_-_SEA_T_T.pptx` — **the rulebook**
14 slides of analyst procedure. This is *knowledge*, not data. It tells you how to interpret a hit, not what the hits are. Becomes ~20 rule chunks in Postgres.

### 2.2 `Sample_3_3_-_...xlsx` — **three searchable databases**
Three sheets, each a table to search against:
- `DESC` — entity master: legal names, aliases, domicile, GUP, **designations**
- `WBS` — engagement listing (actual chargeable work)
- `COT` — Client Onboarding Tool requests

### 2.3 `Sample_3_1_-_12246557.pdf` — **a completed case, with the answer key**
68 pages. A DCCS "Request Management" export for request **12246557**, already worked and closed by a human analyst. It contains three distinct things:

**(a) The case input** — engagement details, engagement team, and three client-side entities with explicit roles:

| Entity | Role stated in request | Location | Designation stated in request |
|---|---|---|---|
| KDDI (Thailand) Limited | Client | Thailand | Do Not Know |
| KDDI Asia Pacific Pte Ltd | Shareholder | Singapore | Relationship |
| KDDI CORPORATION | Global Ultimate Parent | Japan | Restricted |

**(b) A fourth searchable database** — the `DCCS Search Results` tables, ~9,800 rows across the three entities. Columns: `Request Id, Request Type, Service/Type, Entity Name, Side, Entity Role, Status, Date, Lead Partner, Description`. This is the DCCS-history source that QRC slide 10 requires. It is real data and must be ingested as a searchable table, not treated as prose.

**(c) The ground truth** — the analyst's actual determination:
```
Review And Determination
  Final Result   : Approved with Conditions
  Conditions     : Relationship client in DESC
  Comments       : Listed in DESC
                   Local WBS: Non-Assurance
                   WBS & COT match

Cross Border Requests
  Japan → Request Not Required
  Comments: Listed in DESC
```

**(c) is why this file matters more than anything else you have.** It gives you a labelled example. Your pipeline's output can be diffed against a known-correct human answer, which turns "the demo looked good" into a measurable accuracy claim. Build the eval harness (§8) — it is the highest-value thing in this project after the core pipeline.

### 2.4 There is no upload feature
All three files are ingested **offline**, once, by `scripts/run_ingestion.py`. Do not build a file-upload endpoint, a PDF-upload UI, or runtime PDF parsing. Cases come from the ingested PDF or from a manual entry form.

---

## 3. Why there is no vector database

An earlier draft specified Qdrant plus `sentence-transformers`. That was wrong for this problem, and it is also impractical if Claude is your only model — Anthropic does not offer an embedding endpoint (their docs point to Voyage AI as a third-party provider).

Look at every retrieval task in the system:

| Task | Correct mechanism | Semantic? |
|---|---|---|
| Find "KDDI Corporation" in DESC / WBS / COT | fuzzy string matching (`rapidfuzz`) | No — this is string similarity, and embeddings actively hurt: they'd rank "Telkomsel" near "KDDI" as fellow telecoms |
| Search ~9,800 DCCS history rows | SQL `WHERE` + fuzzy name match | No |
| Get the rule governing a WBS match | dict lookup keyed by `source_db` | No — you know exactly which rule you need |
| Analyst asks an open procedural question | Postgres full-text search over ~20 chunks | No — at this corpus size, FTS matches or beats embeddings |

**The rulebook is twenty chunks.** You could paste the entire thing into a single Claude prompt. Semantic retrieval over twenty documents adds latency, a container, a 2 GB torch download, and a failure mode, in exchange for nothing.

**Decision: Postgres only.** Rule retrieval uses a `tsvector` column with GIN index. Entity matching uses `pg_trgm` + `rapidfuzz`. No Qdrant, no embeddings, no torch.

*If judges specifically expect a vector DB:* add `pgvector` to the Postgres you already run and embed the 20 chunks via Voyage AI or OpenAI. ~30 minutes. Treat it as optional polish, not core.

---

## 4. Domain glossary

Coding agents will invent plausible-but-wrong meanings for these. Definitions are from the QRC and the sample request.

| Term | Meaning |
|---|---|
| **DCCS** | Deloitte Conflict Check System — where requests originate and results are issued |
| **DESC** | Entity master. Holds legal names, aliases, domicile, GUP, and **designations**. Authoritative: DESC overrides what a request claims (QRC slide 4) |
| **WBS** | Engagement listing — actual chargeable work, one row per engagement code |
| **COT** | Client Onboarding Tool — in-flight onboarding requests |
| **DCCS Search Results** | Prior conflict-check and cross-border requests involving the same entities. Comes from the sample PDF |
| **One Window** | SharePoint holding Strategic Client, Directorship, Sanctions, Open Opportunities. **No data provided — stubbed** |
| **GUP** | Global Ultimate Parent |
| **LCSP / RP** | Lead Client Service Partner / Responsible Party |
| **Designation** | DESC flag: `Relationship`, `DTT Restricted`, `SEC Restricted`, `EUPIE Restricted`, `Reverse Restricted`, `Watchlist`, `Loan Rule`, `Business Relationship Restricted`, `Audit Team Restricted` |
| **Entity Role** | Role within a request: `Client`, `Shareholder`, `Global Ultimate Parent`, `Intermediate Parent`, `Client Subsidiary`, `Client Side Entity`, `Principal Operating Entity`, `Target` |
| **Relevant parties** | Client side: client, controlling shareholder, GUP, individual controlling the GUP. Other side: the same four (QRC slide 4) |
| **Cross-border check** | Request to another member firm when the client or GUP is foreign (QRC slide 11) |
| **Logging Request** | Cross-border variant sent when the client is in DESC as Relationship or Restricted |
| **Business unit nature** | Each WBS match is labelled `Audit`, `Assurance`, or `Non-Assurance` per QRC slide 6 |
| **Table summary result** | The analyst-facing table of relevant matches — a primary output |

---

## 5. End-to-end pipeline

### Phase 0 — Ingestion (offline, `scripts/run_ingestion.py`)

```
Sample_3_3.xlsx ─┬─ DESC ──► desc_entities        (+ pg_trgm index, full row in JSONB)
                 ├─ WBS  ──► wbs_engagements
                 └─ COT  ──► cot_requests

Sample_3_1.pdf ──► pdftotext -layout ──► section splitter
                 ├─► cases + case_parties            (the request itself)
                 ├─► dccs_search_results             (~9,800 rows — 4th DB)
                 └─► golden_cases                    (the analyst's answer key)

QRC .pptx ──► python-pptx ──► semantic chunker (~20 chunks)
                 └─► rule_chunks (Postgres, tsvector GIN index + dict lookup by source_db)
```

### Phase 1 — Screening (the multi-agent graph)

```
                          ScreeningState
                                │
                 ┌──────────────▼──────────────┐
                 │      ORCHESTRATOR AGENT     │
                 │  • QC: service offering vs  │  QRC slide 3
                 │    engagement details       │
                 │  • QC: referral / IWRF      │  QRC slide 3
                 │  • QC: relevant-party       │  QRC slide 4
                 │    completeness             │
                 │  • emit search plan         │
                 └──────┬───────────────┬──────┘
                        │ parallel fan-out
       ┌────────────────▼───┐      ┌────▼─────────────────────┐
       │   SEARCH AGENT     │      │  RULES & COMPLIANCE      │
       │ tools:             │      │  AGENT                   │
       │  search_desc       │      │ • get_rules_by_source()  │
       │  search_wbs        │      │ • deterministic classify │
       │  search_cot        │      │   via rules_engine       │
       │  search_dccs_hist  │REAL  │ • LLM only for "is this  │
       │  search_one_window │STUB  │   the same legal entity?"│
       │ • DESC-first: diff │      │ • cross-border matrix    │
       │   DESC vs stated   │      │                          │
       │ • 1-level GUP      │      │                          │
       │   expansion        │      │                          │
       └────────────────┬───┘      └────┬─────────────────────┘
                        └───────┬───────┘
                 ┌──────────────▼──────────────┐
                 │     SYNTHESIS AGENT         │
                 │  • dedupe across sources    │
                 │  • build table summary      │
                 │  • derive conditions        │
                 │  • pick final result        │
                 │  • compose draft response   │
                 │  • append slide-14 footer   │
                 │    VERBATIM                 │
                 └──────────────┬──────────────┘
                                ▼
                     screenings + matches rows
```

### Phase 2 — Delivery
```
GET /screenings/{id} ──► React result screen (polled every 2s while RUNNING)
POST /chat           ──► same graph, chat entry, with agent-trace panel
GET  /eval/{case_id} ──► pipeline output vs golden answer, side by side
```

---

## 6. Division of responsibility

| Layer | Owner | Directory |
|---|---|---|
| Postgres schema, ETL (xlsx + pdf + pptx), repositories, rules engine | **Dev A** | `app/models`, `app/repositories`, `app/ingestion`, `app/rules` |
| LangGraph agents, tools, prompts, `ScreeningService`, eval harness | **Dev B** | `app/agents`, `app/services`, `app/eval` |
| FastAPI controllers, DTOs, React app | **Dev C** | `app/controllers`, `app/schemas`, `frontend/` |

Interface points, and nothing else, cross these boundaries:
- **A → B**: `search_desc/wbs/cot/dccs_history`, `search_all`, `search_rules`, `get_rules_by_source`, `get_cross_border_table`, `get_footer_text`, all `rules_engine` functions, `golden_repository.get(case_id)`
- **B → C**: `run_screening(case_id) -> screening_id`, `chat(session_id, case_id, message) -> ChatTurnResult`, `evaluate(case_id) -> EvalResult`
- **A → C**: `case_repository`, `screening_repository`, `entity_search`, `rule_repository` (read-only in controllers)

---

## 7. The rule that governs every design decision

The QRC contains two kinds of instruction, handled differently:

**Mechanical rules → deterministic Python, never LLM reasoning.**
WBS business-unit classification (slide 6), WBS status handling (slide 6), COT 15-Jul-2025 cutoff (slide 9), cross-border matrix (slide 11), DCCS 2-year staleness and status tests (slide 10). These are lookups. They live in `app/rules/rules_engine.py` and return a slide citation with every verdict.

**Judgment calls → LLM.**
Is the service offering consistent with the engagement details? Are all relevant parties present? Is this fuzzy hit the same legal entity given country and GUP context? How should the draft response read?

If an agent prompt asks the model to decide something in the first list, that is a bug. This split makes the output auditable and is the biggest single factor in whether the demo survives scrutiny.

---

## 8. Ground truth and the eval harness

Case **12246557** is fully worked. `golden_cases` stores:

```json
{
  "case_id": "...",
  "request_id": "12246557",
  "final_result": "Approved with Conditions",
  "conditions": ["Relationship client in DESC"],
  "analyst_comments": ["Listed in DESC", "Local WBS: Non-Assurance", "WBS & COT match"],
  "cross_border": [
    { "jurisdiction": "Japan", "outcome": "Request Not Required", "comment": "Listed in DESC" }
  ]
}
```

`app/eval/run_eval.py` runs the pipeline on the case and scores:

| Check | Pass condition |
|---|---|
| Final result | pipeline `final_result` == `APPROVED_WITH_CONDITIONS` |
| Condition detected | a condition mentioning a DESC Relationship designation is present |
| WBS nature | every WBS match classified `Non-Assurance` |
| COT match found | at least one COT match included |
| Cross-border Japan | outcome is "not required" because the GUP is listed in DESC |

Report as a simple pass/fail table. **Show this in the demo.** "We reproduced the analyst's determination on a real closed case" is a far stronger claim than any UI.

---

## 9. Worked example — expected output for case 12246557

**Input** (from the ingested PDF): request 12246557, service offering `Technology & Transformation \ Human Capital \ Organization & Work Transformation`, originator Malaysia, engagement `JO-9671950 – HR Transformation (Ph1)`, not a referral, three client-side entities as listed in §2.3.

**Orchestrator**
- Service offering is T&T and the engagement is an HR transformation — consistent, no flag.
- Not an inbound referral, so no IWRF check needed.
- Relevant parties: Client, Shareholder, and GUP are all present. Individual controlling the GUP is absent → `INFO` flag citing slide 4.
- Search plan: all three entity names.

**Search agent**
- DESC hit: `KDDI CORPORATION`, Japan, designation `Audit Team Restricted, Relationship`, GUP `KDDI CORPORATION`, RP `Manabe, Hiroyuki (JP - Tokyo)`.
- **DESC contradicts the request.** The request states this entity's designation is `Restricted`. DESC says `Audit Team Restricted, Relationship`. Per slide 4, DESC wins → emit a `WARN` flag. The human analyst reached the same conclusion: their final condition reads `Relationship client in DESC`.
- DESC hit: `KDDI (THAILAND) COMPANY LIMITED`, Thailand, designation `Relationship`, same GUP. Note the request calls it `KDDI (Thailand) Limited` — the fuzzy matcher must connect these two.
- WBS: four ongoing engagements (VN ×2, ID, SG).
- COT: four onboarding requests (VN, PH, SG, MY).
- DCCS history: many prior requests across all three entities.
- One Window: stub → recorded in `unchecked_sources`.

**Rules agent**

| Match | Rule | Result |
|---|---|---|
| DESC `KDDI CORPORATION` | slide 5 | `Audit Team Restricted`, `Relationship` |
| WBS `KDDI - BCC ACCOUNTING ADVISORY` (VN) | slide 6 — L1 is A&A but L4 is `A&A: ASV-Accounting & Reporting`, **not** `AUD-Large & Complex` → fallthrough rule (d) | **Non-Assurance**, Ongoing |
| WBS ×3 (T&L) | slide 6 | Non-Assurance, Ongoing |
| COT ×4 | slide 9 — all post-date 15 Jul 2025 | Included, forced Non-Assurance + Ongoing |
| DCCS history rows older than 2 years, or status `Opportunity Lost` / `Engagement Complete` | slide 10 | Excluded, with reasons |
| DCCS history rows already covered by WBS/COT | slide 10 | Deduped |
| Cross-border, Japan | slide 11 — GUP is in DESC | **No additional steps required** → "Request Not Required" |

⚠️ **The WBS row is the canary.** A naive implementation sees `Audit & Assurance` in L1 and labels it Audit. Slide 6 makes A&A count as Audit only when L4 is `AUD-Large & Complex` **and** the WBS text contains `Statutory` or `Financial Statement`. Neither holds. The human analyst wrote `Local WBS: Non-Assurance` — that is your answer key. If your pipeline says Audit, the classifier is wrong.

⚠️ **The COT cutoff never fires on this data** — every COT row is a 2026 submission. Prove the slide-9 rule with a synthetic fixture and say so in the demo.

**Synthesis agent** — target output:
```jsonc
{
  "final_result": "APPROVED_WITH_CONDITIONS",
  "conditions": ["Relationship client in DESC"],
  "quality_check_flags": [
    { "severity": "WARN",
      "message": "Request states KDDI CORPORATION designation as 'Restricted'; DESC shows 'Audit Team Restricted, Relationship'. DESC is authoritative.",
      "action": "Contact requestor to clarify; if the requestor confirms the submitted value, escalate to SEAIndependence@deloitte.com copying the assigned Senior Analysts from the Conflicts and DESC teams",
      "rule_citation": "QRC slide 4" },
    { "severity": "INFO",
      "message": "Individual controlling the GUP not listed among relevant parties",
      "action": "Confirm relevant-party completeness with the requestor",
      "rule_citation": "QRC slide 4" }
  ],
  "summary_table": [ /* DESC, WBS ×4, COT ×4, relevant DCCS history */ ],
  "excluded_matches": [ /* stale + lost + deduped DCCS rows, each with a reason */ ],
  "cross_border_actions": [
    { "jurisdiction": "Japan", "outcome": "Request Not Required",
      "reason": "GUP (KDDI CORPORATION) is listed in DESC",
      "rule_citation": "QRC slide 11" }
  ],
  "unchecked_sources": [
    { "source": "ONE_WINDOW",
      "reason": "Strategic Client / Directorship / Sanctions / Open Opportunities data not provided" }
  ],
  "draft_response": "…narrative…\n\n<verbatim slide-14 DPM 1420 footer + Personal Conflicts>"
}
```

---

## 10. Draft response structure (QRC slide 13)

```
1. Opening — request ID, client entity, service offering, requesting location
2. Relationships identified — the table summary, grouped by source
3. Conditions to be satisfied
4. Cross-border actions required
5. Sources not checked in this build (honesty section)
6. ── Reminders ──
   [DPM 1420 marketplace business relationship text, VERBATIM from slide 14]
7. ── Personal Conflicts ──
   [Personal Conflicts paragraph, VERBATIM from slide 14]
```

Sections 6 and 7 are string-concatenated from `get_footer_text()`. The QRC states this footer applies to **all** SEA T&T cases. The LLM must never generate, summarise, or paraphrase it.

---

## 11. Non-goals — do not build these

- File upload of any kind
- A vector database or embedding pipeline
- Live integration with real DCCS, DESC, WBS, COT, or SharePoint
- Authentication, user accounts, roles
- Auto-submitting results or auto-sending cross-border requests
- Email notifications (Directorship notifications to BRL are surfaced as a required action, not sent)
- Anything that makes an approval decision without an analyst in the loop
- Multi-tenancy or a permissions model

---

## 12. Honest limitations to state in the demo

Say these out loud. A visible gap reads as engineering judgment; a hidden one reads as a bug when a judge finds it.

1. **One Window is not connected** — no data provided. Architecture takes it as one more tool.
2. **We have one worked case**, not a test set. The eval proves reproduction, not generalisation.
3. **The COT cutoff rule has no negative case** in the sample data — proven with a synthetic fixture.
4. **"Recently completed" is undefined in the QRC** (slide 6). We assume 180 days and surface the assumption rather than burying it.
5. **This drafts, it does not approve.** Every classification carries a slide citation so an analyst can overturn it.

---

## 13. Definition of done

- [ ] `docker compose up -d` → `python scripts/run_ingestion.py` → `uvicorn` → `npm run dev` works from a clean clone
- [ ] All four data sources ingested: DESC, WBS, COT, DCCS history
- [ ] Case 12246557 and its golden answer are in the database
- [ ] Screening on 12246557 completes in under 90 seconds
- [ ] Every summary-table row displays a QRC slide citation
- [ ] The WBS canary classifies as Non-Assurance
- [ ] The DESC-vs-request designation contradiction is caught and flagged
- [ ] Cross-border Japan resolves to "not required"
- [ ] Eval harness prints a pass/fail table against the golden answer
- [ ] Draft response ends with the byte-identical slide-14 footer
- [ ] No Qdrant, no `sentence-transformers`, no torch anywhere in the dependency tree
- [ ] The 5-minute demo script has been rehearsed once, end to end, on the presenting machine
