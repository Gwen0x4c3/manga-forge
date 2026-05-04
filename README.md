# MangaForge

AI-powered manga continuation system — import existing manga, understand the story, generate new episodes with consistent characters and plot.

> 用户导入既有漫画（图片/分集）与世界观资料后，系统自动完成「剧情理解 → 资产化 → 长期记忆 → 分镜脚本 → 生图 → 排版」，并支持按集数进行版本控制（branch/fork）的开源 AI 漫画续画系统。

## Architecture

```
Browser (React SPA)          FastAPI (API Server)           Celery Workers
┌──────────────────┐        ┌──────────────────────┐      ┌─────────────────┐
│  Semi UI         │  HTTP  │  Routers / Services   │      │  Understand     │
│  TailwindCSS     │◄──────►│  SQLAlchemy 2.0 async │      │  Script Gen     │
│  TanStack Query  │        │  Pydantic v2          │      │  Render (M2)    │
│  Zustand         │        └──┬───┬───┬────────────┘      │  Layout (M2)    │
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
| Task Queue | Celery + Redis | 5.4+ / 7.x |
| Frontend | React + TypeScript | 19 / 5.x |
| UI Library | Semi UI + TailwindCSS | 2.x / 4.x |
| Build | Vite | 6.x |
| State | Zustand + TanStack Query | 5.x / 5.x |
| Database | MySQL | 8.0+ |
| Vector DB | Qdrant | 1.x |
| Object Storage | MinIO | S3-compatible |
| Container | Docker Compose | — |

## Quick Start

### Prerequisites

- Python 3.12+
- Node.js 18+
- Docker & Docker Compose

### 1. Clone & Install

```bash
git clone https://github.com/your-org/manga-forge.git
cd manga-forge
make install
```

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
│   │   │   ├── core/           # LLM client, vector store, dependencies
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
│   ├── tasks/                  # understand, script_gen, render, layout, ocr
│   ├── pipelines/              # import_pipeline, generate_pipeline
│   └── celery_app.py
├── docker/                     # Docker Compose configs
│   ├── docker-compose.yml
│   ├── docker-compose.dev.yml
│   └── mysql/init.sql
├── docs/                       # Design documents
│   ├── PRD.md
│   ├── design.md
│   └── architecture.md
├── .env.example
└── Makefile
```

## Core Features

### Three-Layer Memory System

| Layer | Storage | Description |
|-------|---------|-------------|
| **Canon Rules** | MySQL `projects.canon_rules` | Hard settings, manually edited |
| **Long Summary** | MySQL `projects.long_summary` | Compressed historical summary, auto-maintained |
| **Recent Window** | MySQL `episode_memories` | Detailed summaries of recent N episodes |
| **RAG** | Qdrant vector DB | Semantic search across all episode memories |

### Episode Understanding Pipeline

Import manga pages → Celery task triggers LLM → extracts structured understanding:

- **Summary** — episode synopsis
- **Events** — key events in chronological order
- **State Changes** — character attribute changes (injury, relationship, possession, etc.)
- **New Assets** — discovered characters, outfits, locations, items
- **Pit Discoveries** — foreshadowing and unresolved plot threads

Results are vectorized and stored in Qdrant for RAG retrieval.

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

### Branch / Fork System

Episodes support DAG parent pointers. Fork from any episode to create alternate storylines with independent memory snapshots.

## API Overview

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET/POST | `/api/v1/projects` | List / Create projects |
| GET/PUT/DELETE | `/api/v1/projects/{id}` | Project CRUD |
| GET/POST | `/api/v1/projects/{id}/episodes` | List / Import episodes |
| POST | `/api/v1/projects/{id}/episodes/import-files` | Upload manga pages |
| GET | `/api/v1/projects/{id}/memory/canon` | Get canon rules |
| PUT | `/api/v1/projects/{id}/memory/canon` | Update canon rules |
| GET | `/api/v1/projects/{id}/memory/summary` | Get long summary |
| GET | `/api/v1/projects/{id}/memory/recent` | Recent episode window |
| POST | `/api/v1/projects/{id}/memory/search` | RAG search |
| GET | `/api/v1/projects/{id}/memory/context` | Generation context |
| POST | `/api/v1/generation/understand` | Trigger episode understanding |
| POST | `/api/v1/generation/script` | Trigger script generation |
| GET | `/api/v1/generation/runs/{id}` | Generation run status |

Full API docs available at `/docs` (Swagger) and `/redoc` when the API server is running.

## Milestones

| Milestone | Status | Description |
|-----------|--------|-------------|
| **M0** | ✅ Done | Project skeleton + data models + basic CRUD |
| **M1** | ✅ Done | Memory system (RAG) + storyboard script generation |
| **M2** | 🔲 Next | Image generation (ComfyUI) + layout + PNG export |
| **M3** | 🔲 | Pit tracking + consistency check + auto-writeback |
| **M4** | 🔲 | Branch fork/diff + asset auto-discovery |

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
| `OPENAI_API_KEY` | | OpenAI API key (required for LLM) |
| `OPENAI_MODEL` | gpt-4o | LLM model for chat |
| `OPENAI_EMBEDDING_MODEL` | text-embedding-3-small | Embedding model |
| `OPENAI_BASE_URL` | | Custom OpenAI-compatible base URL |
| `COMFYUI_URL` | http://localhost:8188 | ComfyUI endpoint (M2) |
| `CELERY_BROKER_URL` | redis://localhost:6379/1 | Celery broker |
| `CELERY_RESULT_BACKEND` | redis://localhost:6379/2 | Celery result backend |

## License

This project is for educational and research purposes only. Users are responsible for ensuring compliance with copyright laws when importing and processing manga content.
