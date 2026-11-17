# MangaForge

AI-powered manga continuation system — import existing manga, understand the story, generate new episodes with consistent characters and plot.

> 用户导入既有漫画（图片/分集）与世界观资料后，系统自动完成「剧情理解 → 资产化 → 长期记忆 → 分镜脚本 → 生图 → 排版」，并支持按集数进行版本控制（branch/fork）的开源 AI 漫画续画系统。

## Architecture

```
Browser (React SPA)          FastAPI (API Server)           Celery Workers
┌──────────────────┐        ┌──────────────────────┐      ┌─────────────────┐
│  Semi UI         │  HTTP  │  Routers / Services   │      │  Understand     │
│  TailwindCSS     │◄──────►│  SQLAlchemy 2.0 async │      │  Script Gen     │
│  TanStack Query  │        │  Pydantic v2          │      │  Render         │
│  Zustand         │        └──┬───┬───┬────────────┘      │  Layout         │
└──────────────────┘           │   │   │                   └────────┬────────┘
                          ┌────┘   │   └────┐                       │
                     ┌────▼──┐ ┌───▼──┐ ┌───▼────┐            ┌─────▼─────┐
                     │ MySQL │ │Qdrant│ │ MinIO  │            │  Redis    │
                     │  8.0  │ │(RAG) │ │ (S3)   │            │ (Broker)  │
                     └───────┘ └──────┘ └────────┘            └───────────┘
```

## Tech Stack

| Layer | Technology | Version |
|-------|-----------|---------|
| Backend | Python / FastAPI | 3.12+ / 0.115+ |
| ORM | SQLAlchemy 2.0 + Alembic | async |
| Structured LLM Output | instructor + OpenAI SDK | 1.0+ / 1.50+ |
| Image Generation | OpenAI Images API / Custom HTTP | gpt-image-2 |
| Task Queue | Celery + Redis | 5.4+ / 7.x |
| Frontend | React + TypeScript | 19 / 5.x |
| UI Library | Semi UI + TailwindCSS | 2.x / 4.x |
| Build | Vite | 6.x |
| State | Zustand + TanStack Query | 5.x / 5.x |
| Database | MySQL | 8.0+ |
| Vector DB | Qdrant | 1.x |
| Object Storage | MinIO | S3-compatible |
| Container | Docker Compose | — |
| Package Manager | uv (Python) / npm (JS) | — |

## Quick Start

### Prerequisites

- [uv](https://docs.astral.sh/uv/) — Python package manager (auto-downloads Python 3.12)
- Node.js 18+ & npm
- Docker & Docker Compose
- **Linux only**: increase inotify watches if `make web` fails with `ENOSPC`:
  ```bash
  echo fs.inotify.max_user_watches=524288 | sudo tee -a /etc/sysctl.conf
  sudo sysctl -p
  ```

### 1. Clone & Install

```bash
git clone https://github.com/your-org/manga-forge.git
cd manga-forge
make install
```

This creates a single `.venv` at the project root via `uv venv`, then installs both `apps/api` and `workers` in editable mode with dev dependencies, and runs `npm install` for the frontend.

> **Why one `.venv`?** The Celery workers import from the API app (`app.models`, `app.services`, etc.) via `sys.path`. A single virtual environment avoids cross-environment import issues and simplifies dependency management.

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env — at minimum set OPENAI_API_KEY
```

### 3. Start Infrastructure

```bash
make infra    # MySQL + Redis + Qdrant + MinIO via Docker Compose
```

### 4. Run Database Migrations

```bash
make migrate
```

### 5. Start Services

```bash
make api      # FastAPI on :8000
make web      # Vite dev server on :5173
make worker   # Celery worker
```

Or start everything:

```bash
make dev
```

### 6. Open Browser

- Frontend: http://localhost:5173
- API Docs: http://localhost:8000/docs

## Project Structure

```
manga-forge/
├── apps/
│   ├── api/                    # FastAPI backend
│   │   ├── app/
│   │   │   ├── core/           # LLM client, image backend, vector store, layout engine
│   │   │   ├── models/         # SQLAlchemy ORM models (11 tables)
│   │   │   ├── prompts/        # Jinja2 prompt templates
│   │   │   ├── routers/        # API route handlers
│   │   │   ├── schemas/        # Pydantic request/response models
│   │   │   └── services/       # Business logic layer
│   │   ├── alembic/            # Database migrations
│   │   └── pyproject.toml
│   └── web/                    # React frontend
│       ├── src/
│       │   ├── pages/          # Page components
│       │   ├── services/       # API client layer
│       │   ├── stores/         # Zustand stores
│       │   └── layouts/        # Layout components
│       └── package.json
├── workers/                    # Celery workers
│   ├── tasks/                  # understand, script_gen, render, layout, writeback, mangadex
│   ├── pipelines/              # continue_pipeline, writeback_pipeline
│   └── pyproject.toml
├── docker/                     # Docker Compose configs
│   ├── docker-compose.yml
│   ├── docker-compose.dev.yml
│   └── mysql/init.sql
├── docs/                       # Design documents
│   ├── PRD.md
│   ├── design.md
│   └── architecture.md
├── .env.example
├── Makefile
└── .venv/                      # Single virtual environment (uv venv)
```

## Core Features

### Three-Layer Memory System

| Layer | Storage | Description |
|-------|---------|-------------|
| **Canon Rules** | MySQL `projects.canon_rules` | Hard settings, manually edited |
| **Long Summary** | MySQL `projects.long_summary` | Rolling historical summary — new episodes are appended, and the LLM re-compresses it once it exceeds the budget (preserving plotline, character states, and unresolved foreshadowing) |
| **Recent Window** | MySQL `episode_memories` | Detailed summaries of recent N episodes |
| **RAG** | Qdrant vector DB (optional) | Semantic search across all episode memories |

> **No embedding model?** Leave `OPENAI_EMBEDDING_MODEL` empty — vectorization is
> skipped and RAG retrieval automatically falls back to keyword search over episode
> memories. Everything else (understanding, generation, pits) works without embeddings.

### Episode Understanding Pipeline (multimodal)

Import manga pages → Celery task sends **the actual page images** to the multimodal LLM (text + vision, e.g. `glm-5.3-flash` via the OpenAI-compatible chat completions protocol) → extracts structured understanding:

- **Summary** — episode synopsis
- **Events** — key events in chronological order
- **State Changes** — character attribute changes (injury, relationship, possession, etc.)
- **Characters (人物识别)** — every character sighted, linked to known assets by ID; new faces are registered as assets with visual tags, and cross-episode appearance tracking (`assets.episode_ids`) is updated automatically
- **Dialogue transcription (OCR)** — all dialogue/narration/SFX transcribed page by page in the original language (no separate OCR stage needed — the vision model reads it directly)
- **Pit Discoveries (伏笔)** — new foreshadowing and unresolved plot threads, deduplicated against existing open pits
- **Pit Resolutions** — open pits clearly resolved by the episode are auto-closed with `resolved_episode_id`

Results feed the three-layer memory: long summary is extended, per-episode memories are stored, and (when an embedding model is configured) vectorized into Qdrant.

### Storyboard Script Generation

Generate structured JSON storyboard for new episodes:

```json
{
  "title": "Episode Title",
  "synopsis": "...",
  "tone": "main",
  "pages": [
    {
      "page_number": 1,
      "layout": "2x2",
      "panels": [
        {
          "panel_id": "1-1",
          "scene": "Classroom, afternoon",
          "characters": [{"name": "Alice", "outfit": "school uniform", "emotion": "determined"}],
          "camera": "medium",
          "dialogue": [{"speaker": "Alice", "text": "Let's go!", "type": "speech"}],
          "prompt": "anime girl in school uniform, determined expression, classroom, afternoon light, manga style"
        }
      ]
    }
  ]
}
```

Context assembly for generation: `canon_rules + long_summary + recent_window + RAG + active_pits + assets`

After generation, a **consistency check** pass reviews the storyboard against canon rules,
character states, and open pits; on critical issues the storyboard is regenerated once with
the issues as feedback. The final report is stored per episode (`consistency_report` memory,
visible in the web UI).

The continue pipeline closes the loop: `script → consistency check → render → layout → writeback`.
Writeback re-runs multimodal understanding on the **rendered pages** of the generated episode,
so new characters, foreshadowing, and pit resolutions from generated content feed the memory
system for the next round of generation.

### Image Generation Pipeline (M2)

Cloud-based image generation with pluggable backends:

| Backend | Description |
|---------|-------------|
| **OpenAI** | GPT-Image-2 / DALL-E 3 via OpenAI Images API |
| **Custom HTTP** | Any cloud API (nanobanana, etc.) via generic HTTP POST adapter |
| **Mock** | Placeholder images for testing |

Generated panel images → Layout engine composes pages with speech bubbles → PNG export to MinIO.

### Branch / Fork System

Episodes support DAG parent pointers. Fork from any episode to create alternate storylines with independent memory snapshots.

## API Overview

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET/POST | `/api/v1/projects` | List / Create projects |
| GET/PUT/DELETE | `/api/v1/projects/{id}` | Project CRUD |
| GET/POST | `/api/v1/projects/{id}/episodes` | List / Import episodes |
| POST | `/api/v1/projects/{id}/episodes/import-files` | Upload manga pages (`auto_understand=true` triggers understanding automatically) |
| GET | `/api/v1/generation/episodes/{id}/export?format=pdf` | Export composed final pages as a single PDF |
| GET/POST | `/api/v1/projects/assets/{id}/images` | List / upload asset reference images (reference / turnaround / lora_dataset) |
| DELETE | `/api/v1/projects/asset-images/{id}` | Delete an asset reference image |
| GET | `/api/v1/projects/{id}/memory/canon` | Get canon rules |
| PUT | `/api/v1/projects/{id}/memory/canon` | Update canon rules |
| GET | `/api/v1/projects/{id}/memory/summary` | Get long summary |
| GET | `/api/v1/projects/{id}/memory/recent` | Recent episode window |
| POST | `/api/v1/projects/{id}/memory/search` | RAG search |
| GET | `/api/v1/projects/{id}/memory/context` | Generation context |
| POST | `/api/v1/generation/understand` | Trigger episode understanding |
| POST | `/api/v1/generation/script` | Trigger script generation |
| POST | `/api/v1/generation/render` | Trigger panel image rendering |
| POST | `/api/v1/generation/layout` | Trigger page layout composition |
| GET | `/api/v1/generation/runs/{id}` | Generation run status |
| GET | `/api/v1/generation/episodes/{id}/images` | List generated images |
| GET | `/api/v1/generation/episodes/{id}/layout` | Get layout result |

Full API docs available at `/docs` (Swagger) and `/redoc` when the API server is running.

## Milestones

| Milestone | Status | Description |
|-----------|--------|-------------|
| **M0** | ✅ Done | Project skeleton + data models + basic CRUD |
| **M1** | ✅ Done | Memory system (RAG) + storyboard script generation |
| **M2** | ✅ Done | Image generation (cloud API) + layout + PNG export |
| **M3** | ✅ Done | Multimodal understanding + pit lifecycle (discover/resolve) + consistency check + auto-writeback |
| **M4** | ✅ Done | Branch fork/diff + asset auto-discovery (embedding-free) |

## Configuration

All configuration via environment variables (see `.env.example`):

| Variable | Default | Description |
|----------|---------|-------------|
| `MYSQL_HOST` | localhost | MySQL host |
| `MYSQL_PORT` | 3306 | MySQL port |
| `MYSQL_USER` | mangaforge | MySQL user |
| `MYSQL_PASSWORD` | mangaforge | MySQL password |
| `MYSQL_DATABASE` | mangaforge | MySQL database |
| `REDIS_URL` | redis://localhost:6379/0 | Redis URL |
| `QDRANT_URL` | http://localhost:6333 | Qdrant URL |
| `QDRANT_COLLECTION` | mangaforge | Qdrant collection name |
| `QDRANT_API_KEY` | | Qdrant API key (optional) |
| `MINIO_ENDPOINT` | localhost:9000 | MinIO endpoint |
| `MINIO_ACCESS_KEY` | minioadmin | MinIO access key |
| `MINIO_SECRET_KEY` | minioadmin | MinIO secret key |
| `MINIO_BUCKET` | mangaforge | MinIO bucket |
| `OPENAI_API_KEY` | | OpenAI API key (required for LLM + image gen) |
| `OPENAI_MODEL` | gpt-4o | Chat model — must support multimodal input (text+images) for understanding, e.g. glm-5.3-flash |
| `OPENAI_EMBEDDING_MODEL` | | Embedding model — **optional**; empty disables vectorization and RAG falls back to keyword search |
| `OPENAI_BASE_URL` | | Custom OpenAI-compatible base URL |
| `IMAGE_BACKEND` | openai | Image backend: openai / custom / mock |
| `IMAGE_MODEL` | gpt-image-2 | Image model (gpt-image-2, dall-e-3, or custom) |
| `IMAGE_API_KEY` | | API key for custom image backend |
| `IMAGE_API_URL` | | URL for custom image backend |
| `IMAGE_DEFAULT_SIZE` | 1024x1024 | Default image generation size |
| `CELERY_BROKER_URL` | redis://localhost:6379/1 | Celery broker |
| `CELERY_RESULT_BACKEND` | redis://localhost:6379/2 | Celery result backend |

## Make Commands

| Command | Description |
|---------|-------------|
| `make install` | Create `.venv`, install Python + JS dependencies |
| `make infra` | Start Docker infrastructure |
| `make down` | Stop Docker infrastructure |
| `make migrate` | Run Alembic migrations |
| `make api` | Start FastAPI dev server (:8000) |
| `make web` | Start Vite dev server (:5173) |
| `make worker` | Start Celery worker |
| `make dev` | Start infra + api + web |
| `make lint` | Run ruff + TypeScript checks |

## License

This project is for educational and research purposes only. Users are responsible for ensuring compliance with copyright laws when importing and processing manga content.
