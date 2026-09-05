# 00 — SHARED SETUP & REQUIREMENTS

**Read `MASTER_overview.md` first.** Everything here is common to all three workstreams. One repo, one venv, one `docker-compose.yml`.

> **Revision note.** Qdrant, `sentence-transformers`, and torch have been **removed**. Rule retrieval uses Postgres full-text search. See `MASTER` §3. If you are working from an older draft, delete those dependencies.

---

## 1. System prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.11 or 3.12 | |
| Node.js | 20 LTS or 22 LTS | for Vite |
| Docker + Compose | v2 | Postgres only |
| **poppler-utils** | any recent | provides `pdftotext`, required for PDF ingestion |
| RAM | 4 GB | modest now that torch is gone |
| Disk | ~2 GB | |

Install poppler:
```bash
# macOS
brew install poppler
# Ubuntu / WSL2 / Debian
sudo apt-get install -y poppler-utils
# verify
pdftotext -v
```

Verify everything:
```bash
python --version && node --version && docker compose version && pdftotext -v
```

---

## 2. Repository bootstrap

```bash
git init conflict-screening && cd conflict-screening
mkdir -p backend/app/{models,repositories,ingestion,rules,agents,services,eval,controllers,schemas}
mkdir -p backend/{scripts,data,tests}
touch backend/app/{__init__.py,config.py,main.py,database.py}
```

Place the three source files in `backend/data/`:
```
backend/data/Sample_3_3_-_12246557_-_Compiled_Databases__1_.xlsx   # DESC / WBS / COT
backend/data/Quick_Reference_Card_-_SEA_T_T.pptx                   # the rulebook, 14 slides
backend/data/Sample_3_1_-_12246557.pdf                             # completed case + DCCS history + answer key
```

⚠️ Use the **unprotected** copy of the PDF. An earlier copy was Purview-encrypted (header `MSMAMARPCRYPT`) and unparseable. Verify with:
```bash
head -c 4 backend/data/Sample_3_1_-_12246557.pdf   # must print %PDF
```

Branching: `main` + `feat/dev-a-data`, `feat/dev-b-agents`, `feat/dev-c-api`. Merge (never rebase) at each checkpoint in §7.

---

## 3. Python dependencies

`backend/requirements.txt`:

```txt
# ---- Web / API ----
fastapi>=0.115,<1.0
uvicorn[standard]>=0.32,<1.0
pydantic>=2.9,<3.0
pydantic-settings>=2.6,<3.0

# ---- Database ----
sqlalchemy>=2.0.36,<3.0
psycopg[binary]>=3.2,<4.0        # psycopg3 driver, NOT psycopg2
alembic>=1.14,<2.0

# ---- Ingestion ----
pandas>=2.2,<3.0
openpyxl>=3.1,<4.0               # .xlsx
python-pptx>=1.0,<2.0            # QRC rulebook
pdfplumber>=0.11,<1.0            # PDF fallback / table extraction
# NOTE: primary PDF path shells out to `pdftotext -layout` (poppler-utils, §1)

# ---- Matching ----
rapidfuzz>=3.10,<4.0

# ---- Agents ----
langgraph>=0.2.50,<1.0
langchain-core>=0.3.20,<1.0
langchain-anthropic>=0.3,<1.0    # or langchain-openai if using GPT

# ---- Utils ----
python-dotenv>=1.0,<2.0
tenacity>=9.0,<10.0

# ---- Dev / test ----
pytest>=8.3,<9.0
pytest-asyncio>=0.24,<1.0
ruff>=0.8,<1.0
```

**Explicitly NOT included, and must not be added:** `qdrant-client`, `sentence-transformers`, `torch`, `chromadb`, `faiss`, `openai` (unless you switch LLM provider). If a coding agent tries to install one of these, it has misread the design — see `MASTER` §3.

```bash
cd backend
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install --upgrade pip && pip install -r requirements.txt
```

Install time is now ~1 minute rather than ~15.

---

## 4. Node dependencies

```bash
npm create vite@latest frontend -- --template react-ts
cd frontend && npm install
npm i react-router-dom@^6.28 @tanstack/react-query@^5.62 axios@^1.7 lucide-react@^0.460 clsx@^2.1
npm i -D tailwindcss@^3.4 postcss@^8.4 autoprefixer@^10.4
npx tailwindcss init -p
npm run dev        # http://localhost:5173
```

Tailwind **v3, not v4** — v4 changed the config format and most setup guidance assumes v3. Don't fight it during a sprint.

---

## 5. Infrastructure — `docker-compose.yml`

```yaml
services:
  postgres:
    image: postgres:16-alpine
    container_name: cs_postgres
    environment:
      POSTGRES_USER: conflict
      POSTGRES_PASSWORD: conflict
      POSTGRES_DB: conflict_screening
    ports: ["5432:5432"]
    volumes: [pgdata:/var/lib/postgresql/data]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U conflict -d conflict_screening"]
      interval: 5s
      timeout: 3s
      retries: 10
volumes:
  pgdata: {}
```

One container. That is the whole infrastructure.

```bash
docker compose up -d && docker compose ps
```

---

## 6. Environment variables

`backend/.env` (git-ignored) and `backend/.env.example` (committed, dummy values):

```bash
# --- Database ---
DATABASE_URL=postgresql+psycopg://conflict:conflict@localhost:5432/conflict_screening

# --- LLM ---
LLM_PROVIDER=anthropic              # anthropic | openai
LLM_MODEL=claude-sonnet-4-5
LLM_TEMPERATURE=0
LLM_MAX_TOKENS=4096
ANTHROPIC_API_KEY=sk-ant-...
# OPENAI_API_KEY=sk-...

# --- Matching thresholds ---
MATCH_THRESHOLD_AUTO_INCLUDE=0.80   # >= goes into the summary table
MATCH_THRESHOLD_REVIEW=0.65         # >= goes to "possible matches" for analyst review
PGTRGM_PREFILTER_THRESHOLD=0.30     # deliberately loose SQL prefilter

# --- Business rules (QRC) ---
COT_CUTOFF_DATE=2025-07-15          # slide 9
DCCS_STALENESS_YEARS=2              # slide 10
WBS_RECENT_COMPLETION_DAYS=180      # our assumption for "recently completed", slide 6

# --- App ---
DATA_DIR=./data
PDFTOTEXT_BIN=pdftotext
CORS_ORIGINS=http://localhost:5173
LOG_LEVEL=INFO
GRAPH_RECURSION_LIMIT=25
```

`frontend/.env`:
```bash
VITE_API_BASE_URL=http://localhost:8000/api/v1
VITE_MOCK_MODE=true
VITE_POLL_INTERVAL_MS=2000
```

Load via `pydantic_settings.BaseSettings` in `app/config.py`. **No threshold or cutoff date may be hardcoded anywhere else.** Judges will ask where 15 July 2025 comes from and you want to point at one line.

---

## 7. Integration checkpoints — everyone merges to `main` here

| When | Gate | Blocked if not met |
|---|---|---|
| **Day 1, hour 1** | Dev C commits `app/schemas/` (the full API contract) | A and B cannot start |
| **Day 1, midday** | Dev A commits repo/rules stubs returning fixtures; Dev B commits `run_screening()` / `chat()` stubs returning fixtures | B blocked on A; C blocked on B |
| **Day 1, EOD** | Ingestion green: DESC/WBS/COT/DCCS-history loaded, rule chunks in Postgres, golden case stored; frontend runs on mocks | Day 2 becomes a scramble |
| **Day 2, midday** | Real repos wired into controllers; graph runs end-to-end on case 12246557 | No time left for the result screen or eval |

**The rule that saves the deadline: nobody waits for a real implementation.** Ship stubs returning the fixture payloads from `DEV_C` §1 immediately, then replace the insides.

---

## 8. Run commands

```bash
docker compose up -d
cd backend && alembic upgrade head
python scripts/run_ingestion.py          # idempotent: truncate + reload all four sources
uvicorn app.main:app --reload --port 8000    # docs at /docs
python -m app.eval.run_eval 12246557     # score against the golden answer
cd ../frontend && npm run dev
cd ../backend && pytest -q
```

---

## 9. Acceptance tests

Write these as `pytest` cases in `backend/tests/`, not manual clicking.

| # | Test | Expected |
|---|---|---|
| 1 | `search_all("KDDI Corporation")` | hits in DESC, WBS, COT, and DCCS history |
| 2 | DESC designation parsing | `KDDI CORPORATION` → `['Audit Team Restricted', 'Relationship']` |
| 3 | Fuzzy name bridging | request's `KDDI (Thailand) Limited` matches DESC's `KDDI (THAILAND) COMPANY LIMITED` above the review threshold |
| 4 | **WBS canary** — `KDDI - BCC ACCOUNTING ADVISORY`, L1 `Audit & Assurance`, L4 `A&A: ASV-Accounting & Reporting` | **Non-Assurance**, not Audit. Slide 6 rule (d) fallthrough. Human analyst's answer key says `Local WBS: Non-Assurance`. If this returns Audit, the classifier is wrong |
| 5 | WBS status | `Released` → `Ongoing`; `Technically Completed` → excluded unless recent audit + still Restricted |
| 6 | COT cutoff | a **synthetic** row before 2025-07-15 lands in `excluded_matches` citing slide 9 |
| 7 | COT inclusion | included COT rows forced to `Non-Assurance` + `Ongoing` |
| 8 | DESC contradiction | request says designation `Restricted`, DESC says `Audit Team Restricted, Relationship` → `WARN` flag naming the SEAIndependence escalation path |
| 9 | DCCS staleness | rows older than 2 years excluded; `Opportunity Lost` and `Engagement Complete` excluded; each with a reason |
| 10 | DCCS dedupe | a DCCS row already represented in WBS/COT is not double-counted |
| 11 | Cross-border | GUP `KDDI CORPORATION` in DESC → Japan resolves to "Request Not Required" |
| 12 | Footer | `draft_response` ends byte-identical to `get_footer_text()` |
| 13 | Unchecked sources | `unchecked_sources` contains One Window only (not DCCS — that one is real now) |
| 14 | Ingestion counts | `dccs_search_results` row count is in the thousands; 3 `case_parties` rows for case 12246557 |
| 15 | Eval | `run_eval 12246557` reports final result, condition, WBS nature, and cross-border all passing |
| 16 | Full run | `POST /screen` → poll → `COMPLETE` in under 90 seconds |
| 17 | Dependency hygiene | `pip freeze` contains no `torch`, `qdrant`, `sentence-transformers`, `chromadb`, `faiss` |

Tests 4 and 15 are the ones that separate a working rules engine from a plausible-looking one. Write them first.

---

## 10. Demo script (rehearse Day 2 evening, 5 minutes)

1. Dashboard — four data sources loaded, with row counts.
2. Open case 12246557 — a real closed request: three client-side entities, roles stated.
3. Run screening. Narrate the four agents while it polls.
4. Result screen — walk the summary table; tap a rule-citation chip to show the QRC slide behind it.
5. **The DESC contradiction.** "The request claims this entity is Restricted. DESC says Relationship. Slide 4 says DESC wins — so we flagged it. The human analyst reached the same conclusion; their final condition reads *Relationship client in DESC*."
6. **The eval screen.** Pipeline output beside the analyst's actual determination. Point at the matching final result and the `Local WBS: Non-Assurance` line.
7. Chat: "why was that DCCS match excluded?" → show the agent trace and the retrieved rule.
8. Close on the honest gap: One Window isn't connected, and the architecture takes it as one more tool.

Step 6 is your strongest moment. Do not let it get cut for time.
