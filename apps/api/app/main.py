import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.database import init_db
from app.middleware.response_wrapper import ResponseWrapperMiddleware
from app.routers import assets, branches, episodes, generation, memory, pits, projects, storage

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(
    title="Manga Forge API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(ResponseWrapperMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "code": 500,
            "message": str(exc),
            "data": None,
        },
    )


@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    return JSONResponse(
        status_code=404,
        content={"code": 404, "message": "接口不存在", "data": None},
    )


@app.exception_handler(405)
async def method_not_allowed_handler(request: Request, exc):
    return JSONResponse(
        status_code=405,
        content={"code": 405, "message": "请求方法不允许", "data": None},
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
