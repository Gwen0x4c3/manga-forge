from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from app.config import settings

engine = create_async_engine(settings.mysql_dsn, echo=False, pool_pre_ping=True)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db():
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()


@asynccontextmanager
async def worker_session():
    """Event-loop-safe DB session for Celery tasks and standalone scripts calling asyncio.run().

    Creates a NullPool engine bound only to the current event loop and disposes it cleanly
    before the loop closes, preventing aiomysql 'RuntimeError: Event loop is closed'.
    """
    local_engine = create_async_engine(settings.mysql_dsn, echo=False, poolclass=NullPool)
    maker = async_sessionmaker(local_engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with maker() as session:
            yield session
    finally:
        await local_engine.dispose()
