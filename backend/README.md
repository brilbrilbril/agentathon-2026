# Backend — Dev A (Data Layer, Ingestion & Retrieval)

## Setup

```bash
# from repo root
docker compose up -d

cd backend
python -m venv .venv && source .venv/Scripts/activate   # Windows Git Bash
pip install -r requirements.txt
cp .env.example .env    # defaults already point at the docker-compose Postgres (port 5434)

alembic upgrade head
python scripts/run_ingestion.py
pytest -q
```

Postgres runs on **port 5434** (not the default 5432) to avoid clashing with
other local Postgres containers on this machine.

## What's implemented (Dev A scope)

- `app/models/domain.py` — shared domain models (`EntityMatch`, `RuleChunk`, etc.)
- `alembic/versions/` — full schema: DESC/WBS/COT, `dccs_search_results` (4th DB,
  parsed from the PDF), `cases`/`case_parties`, `golden_cases`, `rule_chunks`,
  `screenings`/`matches`, `chat_sessions`/`chat_messages`
- `app/ingestion/` — `xlsx_loader.py` (DESC/WBS/COT), `pdf_loader.py` (DCCS
  export: case header, 3 case parties, ~3,500 DCCS history rows, golden
  answer), `qrc_loader.py` (19 rule chunks from the QRC pptx)
- `app/rules/rules_engine.py` — deterministic QRC rule lookups (WBS
  business-unit/status classification, COT cutoff, DCCS staleness,
  cross-border matrix, DESC-vs-request comparison), every function cites its
  QRC slide
- `app/repositories/` — `entity_search.py` (pg_trgm + rapidfuzz two-stage
  matching), `rule_repository.py` (dict lookup + FTS fallback + verbatim
  footer), `case_repository.py`, `golden_repository.py`,
  `screening_repository.py`, `chat_repository.py`
- `scripts/run_ingestion.py` — idempotent ETL entrypoint

## Verified against case 12246557's known ground truth

Running `scripts/run_ingestion.py` against the real sample data reproduces:
- 3 case parties with roles Client / Shareholder / Global Ultimate Parent
- The DESC-vs-request designation contradiction (request says `Restricted`,
  DESC says `Audit Team Restricted, Relationship`)
- The WBS canary (`A&A: ASV-Accounting & Reporting` → Non-Assurance, not Audit)
- Cross-border Japan → "Request Not Required" (GUP listed in DESC)
- The analyst's actual final result, conditions, and comments in `golden_cases`

## Not implemented here (Dev B / Dev C scope)

LangGraph agents, FastAPI routes, and the React frontend are out of scope for
this workstream — see `DEV_B_multi_agent_system.md` and
`DEV_C_api_and_frontend.md`. The functions this layer exposes to them are
listed in `MASTER_overview.md` §6.
