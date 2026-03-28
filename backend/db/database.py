"""
Async PostgreSQL connection pool using asyncpg.
All agents and routers use `get_db()` as a FastAPI dependency.
"""
import asyncpg
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from core.config import settings

logger = logging.getLogger(__name__)

# Module-level pool — initialized once on startup
_pool: asyncpg.Pool | None = None


async def init_db() -> None:
    """Create connection pool. Called from FastAPI lifespan."""
    global _pool
    _pool = await asyncpg.create_pool(
        host=settings.POSTGRES_HOST,
        port=settings.POSTGRES_PORT,
        database=settings.POSTGRES_DB,
        user=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD,
        min_size=3,
        max_size=15,
        command_timeout=30,
    )
    logger.info("PostgreSQL pool created — %s@%s/%s",
                settings.POSTGRES_USER, settings.POSTGRES_HOST, settings.POSTGRES_DB)


async def close_db() -> None:
    """Close pool. Called from FastAPI lifespan on shutdown."""
    global _pool
    if _pool:
        await _pool.close()
        logger.info("PostgreSQL pool closed")


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("Database pool not initialized. Call init_db() first.")
    return _pool


@asynccontextmanager
async def get_connection() -> AsyncGenerator[asyncpg.Connection, None]:
    """Context manager for a single checked-out connection."""
    async with get_pool().acquire() as conn:
        yield conn


async def get_db() -> AsyncGenerator[asyncpg.Connection, None]:
    """
    FastAPI dependency. Usage:
        async def my_route(db: asyncpg.Connection = Depends(get_db)): ...
    """
    async with get_pool().acquire() as conn:
        yield conn


async def execute_schema(schema_path: str = "db/schema.sql") -> None:
    """Run schema.sql on startup if tables don't exist yet."""
    with open(schema_path, "r") as f:
        sql = f.read()
    async with get_connection() as conn:
        await conn.execute(sql)
    logger.info("Schema applied from %s", schema_path)