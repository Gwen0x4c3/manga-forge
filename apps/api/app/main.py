from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import init_db
from app.routers import assets, branches, episodes, generation, memory, pits, projects, storage


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(
    title="MangaForge API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(projects.router, prefix="/api/v1/projects", tags=["Projects"])
app.include_router(episodes.router, prefix="/api/v1/projects", tags=["Episodes"])
app.include_router(branches.router, prefix="/api/v1/projects", tags=["Branches"])
app.include_router(assets.router, prefix="/api/v1/projects", tags=["Assets"])
app.include_router(pits.router, prefix="/api/v1/projects", tags=["Pits"])
app.include_router(memory.router, prefix="/api/v1/projects", tags=["Memory"])
app.include_router(generation.router, prefix="/api/v1/generation", tags=["Generation"])
app.include_router(storage.router, prefix="/api/v1/storage", tags=["Storage"])


@app.get("/health")
async def health_check():
    return {"status": "ok"}
