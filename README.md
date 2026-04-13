# Stark Labs

Stark Labs is a build-review-harden workspace centered around **Mark II Studio**, a full-stack app that takes a product idea or an existing codebase, interviews the user for requirements, generates candidates with multiple LLM providers, judges the result, and then hardens the winning build.

The repo also contains the lower-level `mark_ii` engine, sandbox helpers, and a VS Code extension that can connect to the Studio backend.

## What Mark II Studio does

Mark II Studio is designed around a simple pipeline:

1. Intake
   - Start from a prompt
   - Import a GitHub repository
   - Paste one file or multiple fenced files directly into the UI
2. Interview
   - Claude asks focused follow-up questions
   - Existing code intake is analyzed first, then gaps are clarified
3. Spec review
   - Requirements and blueprint are captured in a structured spec
4. Build
   - Multiple builders can run in parallel
   - Candidates are uploaded to isolated sandboxes
5. Judge
   - Claude compares the candidates and selects a baseline
6. Harden
   - The Mark II loop runs adversarial validation and targeted repairs
7. Delivery
   - Final artifacts, preview, and showcase links are exposed in the UI

## Main capabilities

- Prompt, GitHub, and paste-based project intake
- Reverse interview with Claude for requirement discovery
- Parallel builder execution with OpenAI, DeepSeek, Zhipu, and optional Ollama
- Structured judging of generated candidates
- Live sandbox previews
- API Playground mode for API projects
- Responsive iframe preview mode for web apps
- Hardening loop with patch-based repairs
- SSE-driven session UI for live updates
- VS Code extension under `studio/vscode`

## Supported project types

Out of the box, the profile system recognizes:

- `fastapi_service`
- `nextjs_webapp`

There is also a `dynamic_profile` path for architect-driven blueprints, plus an `unsupported` fallback for analysis-only scenarios.

## Repository layout

```text
stark_labs/
├── mark_ii/                Core hardening and patching engine
├── iron_legion/            Additional strike / suit modules
├── studio/
│   ├── backend/            FastAPI API, orchestration, models, services
│   ├── frontend/           Next.js session UI and showcase UI
│   └── vscode/             VS Code extension
├── .env.example            Environment template
├── docker-compose.yml      Dev services definition
└── README.md               This file
```

## Key backend pieces

- `studio/backend/app/main.py`
  - FastAPI entrypoint
  - Registers routes and CORS
  - Creates database tables on startup for local dev
- `studio/backend/app/api/sessions.py`
  - Session lifecycle endpoints
  - Interview, build, preview, delivery, and SSE orchestration hooks
- `studio/backend/app/services/orchestrator.py`
  - State machine for `created -> interviewing -> spec_review -> building -> judging -> hardening -> complete`
- `studio/backend/app/services/sandbox.py`
  - E2B sandbox lifecycle, preview startup, service URL resolution
- `mark_ii/`
  - Patch planning, repair application, memory, validation, and strike logic

## Key frontend pieces

- `studio/frontend/src/app/page.tsx`
  - Landing page and intake entrypoint
- `studio/frontend/src/app/session/[id]/page.tsx`
  - Main session workspace with Interview / Build / Harden / Delivery tabs
- `studio/frontend/src/components/PreviewSystem.tsx`
  - Sidebar preview renderer
  - Chooses iframe mode for web apps and API Playground mode for API sessions
- `studio/frontend/src/components/ArtifactsViewer.tsx`
  - Delivery artifact browser

## Local development

### Prerequisites

- Python 3.11+ recommended
- Node.js 18+ recommended
- npm

### 1. Configure environment

Copy the example file and fill in the values you actually want to use:

```bash
cp .env.example .env
```

Important notes:

- `OPENAI_API_KEY` is required for the OpenAI builder.
- `ANTHROPIC_API_KEY` is required for the interviewer and judge flows.
- `E2B_API_KEY` is required for real cloud sandbox previews.
- If `DATABASE_URL` is not set, the backend now falls back to a repo-local SQLite database at `markii_studio.db`.

### 2. Install backend dependencies

```bash
cd studio/backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Install frontend dependencies

```bash
cd studio/frontend
npm install
```

### 4. Start the backend

```bash
cd studio/backend
./venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Backend URLs:

- API root: `http://127.0.0.1:8000`
- Docs: `http://127.0.0.1:8000/docs`

### 5. Start the frontend

```bash
cd studio/frontend
npm run dev
```

Frontend URL:

- App: `http://localhost:3000`

## Environment variables

The main variables used by the current codebase are:

- `OPENAI_API_KEY`
- `ANTHROPIC_API_KEY`
- `DEEPSEEK_API_KEY`
- `ZHIPU_API_KEY`
- `E2B_API_KEY`
- `DATABASE_URL`
- `REDIS_URL`
- `OPENAI_BUILDER_MODEL`
- `DEEPSEEK_BUILDER_MODEL`
- `CLAUDE_JUDGE_MODEL`
- `CLAUDE_INTERVIEWER_MODEL`
- `DEEPSEEK_BASE_URL`
- `ZHIPU_BASE_URL`
- `PRODUCT_NAME`

## Preview behavior

The preview sidebar supports two modes:

- `iframe`
  - Used for web applications such as Next.js projects
- `api_playground`
  - Used for API-style previews such as FastAPI services

Preview requests are proxied through the backend so the UI does not depend on browser CORS behavior when talking to sandboxed services.

## Paste intake format

The home page supports:

- Direct single-file paste
- Multi-file fenced paste

Example:

````text
File: app/page.tsx
```tsx
export default function Page() {
  return <main>Hello</main>;
}
```

File: package.json
```json
{
  "dependencies": {
    "next": "14.2.21"
  }
}
```
````

If no filename is provided, the frontend infers one from the content when possible.

## Data and persistence

- The backend uses SQLAlchemy async sessions.
- Local dev can run entirely on SQLite.
- The SQLite file normally lives at the repo root as `markii_studio.db`.
- Postgres and Redis service definitions are included in `docker-compose.yml`.

## VS Code extension

The extension lives under `studio/vscode` and is intended to connect to the same backend session system used by the web UI.

## Known operational notes

- Do not commit `.env`.
- Real sandbox previews depend on valid E2B credentials.
- The frontend runs on port `3000`; the backend runs on port `8000`.
- Some workflows can boot locally without all providers configured, but missing API keys will disable or degrade the corresponding features.
- If Anthropic is not configured, interview/spec generation falls back to a reduced auto-generated path.

## Useful commands

Typecheck the frontend:

```bash
cd studio/frontend
./node_modules/.bin/tsc --noEmit -p .
```

Compile-check backend modules:

```bash
cd /path/to/stark_labs
PYTHONPYCACHEPREFIX=/tmp/pycache python3 -m py_compile \
  studio/backend/app/settings.py \
  studio/backend/app/database.py \
  studio/backend/app/api/sessions.py \
  studio/backend/app/services/orchestrator.py
```

Run the sandbox manager test:

```bash
cd studio/backend
./venv/bin/python -m unittest test_sandbox_manager.py
```

## Git

This repository is now initialized as its own git repo and ignores:

- `.env`
- local databases
- logs
- Python virtual environments
- `node_modules`
- Next.js build output

That keeps local runtime state out of commits while preserving the actual app source.
