# Conflict Screening Multi-Agent Assistant

A conflict-of-interest screening assistant for Deloitte SEA Tax & Transformation analysts.
It searches four conflict databases, applies the QRC rulebook, triages what it finds, and
drafts the response — with a human analyst as the decision-maker.

**It drafts, it does not approve.** Every conclusion cites the rulebook slide it came from.

| | |
|---|---|
| Business overview (no technical background needed) | [`OVERVIEW_FOR_BUSINESS.md`](OVERVIEW_FOR_BUSINESS.md) |
| Architecture, tools, pipeline, design decisions | [`backend/README.md`](backend/README.md) |
| Recorded agent Q&A — 18 questions, real tool calls | [`QA_TRANSCRIPT.md`](QA_TRANSCRIPT.md) |

---

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.11 or 3.12 | |
| Node.js | 20 LTS or newer | for Vite |
| Docker + Compose | v2 | Postgres only |
| **`pdftotext`** | any recent | required for PDF ingestion — see below |
| An OpenAI-compatible LLM server | — | see [Inference](#inference) below |

### `pdftotext`

Ingestion shells out to `pdftotext` to turn the DCCS PDF export into text. Either
**poppler-utils** or **Xpdf** provides it — they share the command and the `-layout`
and `-enc` flags this project uses (poppler is a fork of Xpdf).

**Check whether you already have it before installing anything:**

```bash
pdftotext -v
```

On Windows it is often already present: Git for Windows and Sourcetree both bundle a copy
in their `mingw64/bin`, which usually ends up on PATH.

If it's missing:

```bash
# macOS
brew install poppler

# Ubuntu / WSL2 / Debian
sudo apt-get install -y poppler-utils

# Windows — any one of these
winget install --id oschwartz10612.Poppler      # winget, ships with Windows 10/11
scoop install poppler                           # if you use scoop
choco install poppler                           # if you use Chocolatey
# or download the Xpdf command-line tools from https://www.xpdfreader.com/download.html
# and add the folder containing pdftotext.exe to your PATH
```

Only **ingestion** needs it. Once the data is in Postgres, the API, agents and UI never
touch it again — so a teammate running the app against an already-loaded database can skip
this entirely.

The three source files (xlsx, PDF, pptx) are committed under `sample_dataset/` and
`reference/`, so there is nothing else to download.

---

## Run it

```bash
git clone <this-repo> && cd agentathon-2026

# 1. Postgres (port 5434, to avoid clashing with any local Postgres you already run)
docker compose up -d

# 2. Backend
cd backend
python -m venv .venv
source .venv/Scripts/activate          # Windows Git Bash
# source .venv/bin/activate            # macOS / Linux
pip install -r requirements.txt
cp .env.example .env

alembic upgrade head                   # create the schema
python scripts/run_ingestion.py        # load all four sources (~30s, idempotent)
pytest -q -m "not slow"                # 100 tests, no LLM needed

uvicorn app.main:app --reload --port 8000     # API docs at /docs

# 3. Frontend (new terminal)
cd frontend
npm install
cp .env.example .env
npm run dev                            # http://localhost:5173
```

Ingestion should report:

```
Summary — DESC: 2, WBS: 14, COT: 7, DCCS history: 3907, case_parties: 3, rule_chunks: 19
```

---

## Inference

Anything that speaks the OpenAI chat-completions API **with tool calling**. Defaults point
at a local `llama.cpp` server:

```bash
# in backend/.env
LLM_BASE_URL=http://localhost:8080/v1
LLM_MODEL=Qwen3.5-4B
LLM_API_KEY=sk-no-key-required
```

### Running llama.cpp locally

```bash
# build or install llama.cpp, then serve a tool-calling capable GGUF model.
# --jinja is REQUIRED: without it the server won't parse tool calls and every
# agent degrades to answering with no tools.
llama-server -m /path/to/Qwen3.5-4B.gguf --jinja --port 8080 -c 65536
```

Verify with:

```bash
curl -s http://localhost:8080/v1/models          # should list your model
curl -s http://localhost:8000/api/v1/health      # should report "llm": true
```

### Using a hosted provider instead

Point `LLM_BASE_URL` at any OpenAI-compatible endpoint and set `LLM_API_KEY`. Screening is
much faster on a larger model — the 40–120s figures in the docs are for a 4B model on CPU.

### With no LLM at all

Ingestion, the schema, the deterministic QRC rules, the API and the whole test suite work
without an inference server. Agents degrade to empty runs and say so; `/health` reports
`"llm": false`. Only chat and screening need the model.

---

## Verify it works

```bash
cd backend
pytest -q -m "not slow"                  # 100 tests, no LLM required
python -m app.eval.run_eval 12246557     # scores the pipeline against a real analyst's answer
python scripts/qa_smoke.py --md ../QA_TRANSCRIPT.md   # 18 analyst questions, writes a transcript
```

`run_eval` reproduces the determination a human analyst actually recorded on closed case
12246557 — final result, conditions, the WBS canary, cross-border, risk triage, and the
DESC-contradiction flag. Eight checks. That is the strongest claim in the project: not
"the demo looked good" but "we reproduced a known-correct human answer".

---

## Opening it from another device

Both dev servers bind all interfaces, and the frontend talks to whichever host served the
page, so a laptop or phone on the same network works without extra config:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
npm run dev            # vite already binds 0.0.0.0
```

Then browse to `http://<this-machine-ip>:5173`. CORS accepts private-range origins
(`CORS_ORIGIN_REGEX` in `.env`) and rejects public ones.

---

## Layout

```
backend/
  app/agents/       four agents, the tool registry, the tool-calling runtime
  app/rules/        deterministic QRC rules — every mechanical verdict lives here
  app/repositories/ pg_trgm + rapidfuzz entity search, rule lookup, CRUD
  app/ingestion/    xlsx / PDF / pptx loaders
  app/controllers/  FastAPI routes
  app/eval/         scores the pipeline against the analyst's answer key
  scripts/          run_ingestion.py, qa_smoke.py
frontend/           Vite + React + Tailwind
sample_dataset/     the three source files
reference/          the QRC rulebook
```

## Troubleshooting

| Symptom | Cause |
|---|---|
| `pdftotext not found on PATH` | no poppler/Xpdf on PATH — see Prerequisites; you may already have one bundled with Git for Windows |
| `connection refused` on port 5434 | `docker compose up -d` hasn't run, or Docker Desktop is stopped |
| `/health` shows `"llm": false` | no inference server reachable at `LLM_BASE_URL` |
| Agent answers without calling tools | llama.cpp started without `--jinja` |
| `No case found for request 12246557` | run `python scripts/run_ingestion.py` |
| Chat history looks empty after `docker compose down -v` | `-v` deletes the Postgres volume; use plain `down` to keep it |
