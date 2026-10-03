"""
PostgreSQL Async Database Session & Engine Management.
Provides connection pooling, health checks, and resilient error isolation.
"""
from __future__ import annotations
import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import declarative_base
from sqlalchemy.pool import NullPool

from backend.core.config import get_postgres_url

logger = logging.getLogger("nexus.database")

Base = declarative_base()

import time
from sqlalchemy.dialects.postgresql.asyncpg import AsyncAdapt_asyncpg_connection
from sqlalchemy.util.concurrency import await_
import asyncio

# Resilient patch for Neon/PgBouncer TLS disconnects:
# When serverless Postgres closes idle connections without full TLS close_notify exchange,
# standard asyncpg close() hangs until timeout. This terminates the socket immediately on timeout.
_orig_asyncpg_close = getattr(AsyncAdapt_asyncpg_connection, "close", None)
def _safe_asyncpg_close(self):
    try:
        self.rollback()
    except Exception:
        pass
    try:
        if hasattr(self, "_connection") and self._connection:
            try:
                await_(asyncio.wait_for(self._connection.close(), timeout=0.8))
            except Exception:
                try:
                    self._connection.terminate()
                except Exception:
                    pass
    except Exception:
        try:
            if hasattr(self, "_connection") and self._connection:
                self._connection.terminate()
        except Exception:
            pass

if _orig_asyncpg_close is not None:
    AsyncAdapt_asyncpg_connection.close = _safe_asyncpg_close

# Suppress noisy pool error logging on discarded connections
logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)

_engine: Optional[AsyncEngine] = None
_session_factory: Optional[async_sessionmaker[AsyncSession]] = None
_last_db_check_time: float = 0.0
_last_db_check_result: bool = False


def get_engine() -> Optional[AsyncEngine]:
    global _engine, _session_factory
    if _engine is not None:
        return _engine

    url = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL") or get_postgres_url()
    if not url:
        return None

    # Ensure async driver (convert postgresql:// or postgres:// to postgresql+asyncpg://)
    if url.startswith("postgres://"):
        url = "postgresql+asyncpg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://") and not url.startswith("postgresql+asyncpg://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://"):]

    try:
        from sqlalchemy.engine import make_url
        parsed_url = make_url(url)
        query = dict(parsed_url.query)

        # Remove query options unsupported by asyncpg's connect() method
        ssl_in_query = "ssl" in query or "sslmode" in dict(parsed_url.query)
        unsupported_keys = ["channel_binding", "sslmode", "gssencmode", "ssl"]
        for key in unsupported_keys:
            query.pop(key, None)

        connect_args = {
            "timeout": 8.0,
            "command_timeout": 10.0,
            "server_settings": {
                "tcp_keepalives_idle": "60",
                "tcp_keepalives_interval": "10",
                "tcp_keepalives_count": "5",
            },
        }
        # CRITICAL FOR NEON & PGBOUNCER POOLERS:
        # Transaction-mode poolers do not support prepared statement caches, which causes asyncpg to hang or timeout.
        if "pooler" in url or "neon.tech" in url or "pgbouncer" in url:
            connect_args["statement_cache_size"] = 0
            connect_args["prepared_statement_cache_size"] = 0

        if ssl_in_query or "neon.tech" in url or "sslmode=" in url:
            connect_args["ssl"] = "require"

        clean_url = parsed_url._replace(query=query).render_as_string(hide_password=False)

        # Use NullPool for serverless cloud databases (e.g. Neon, Supabase) to prevent
        # idle connection drops that trigger asyncpg query/rollback TimeoutErrors in _async_ping.
        _engine = create_async_engine(
            clean_url,
            echo=False,
            poolclass=NullPool,
            connect_args=connect_args,
        )
        _session_factory = async_sessionmaker(
            bind=_engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
        logger.info("[Database] Initialized PostgreSQL async engine.")
        return _engine
    except Exception as exc:
        logger.error(f"[Database] Failed to initialize async engine: {exc}")
        return None


def get_session_factory() -> Optional[async_sessionmaker[AsyncSession]]:
    global _session_factory
    if _session_factory is None:
        get_engine()
    return _session_factory


def AsyncSessionLocal():
    """Create a new async database session."""
    factory = get_session_factory()
    if factory is None:
        raise RuntimeError("Database session factory is not available.")
    return factory()


async def check_db_connection() -> bool:
    """Test whether the PostgreSQL database is reachable with 15s result caching."""
    global _last_db_check_time, _last_db_check_result
    now = time.time()
    if now - _last_db_check_time < 15.0:
        return _last_db_check_result

    engine = get_engine()
    if engine is None:
        _last_db_check_result = False
        _last_db_check_time = now
        return False
    try:
        from sqlalchemy import text
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        _last_db_check_result = True
        _last_db_check_time = now
        return True
    except Exception as exc:
        logger.warning(f"[Database] Connection check failed: {exc}")
        _last_db_check_result = False
        _last_db_check_time = now
        return False


async def get_db_session() -> AsyncGenerator[Optional[AsyncSession], None]:
    """FastAPI dependency for obtaining an async database session with offline/timeout resilience."""
    factory = get_session_factory()
    if factory is None:
        yield None
        return

    session_yielded = False
    try:
        async with factory() as session:
            try:
                session_yielded = True
                yield session
                await session.commit()
            except Exception:
                try:
                    await session.rollback()
                except Exception:
                    pass
                raise
    except Exception as conn_err:
        if not session_yielded:
            logger.warning(f"[Database] Could not acquire session (offline/timeout): {conn_err}")
            yield None
        else:
            raise


@asynccontextmanager
async def safe_db_context() -> AsyncGenerator[Optional[AsyncSession], None]:
    """Context manager for standalone/background tasks with safe exception containment."""
    factory = get_session_factory()
    if factory is None:
        yield None
        return

    session_yielded = False
    try:
        async with factory() as session:
            try:
                session_yielded = True
                yield session
                # Only execute commit if session is active and has pending changes (dirty, new, or deleted)
                if session.is_active and (session.dirty or session.new or session.deleted):
                    await asyncio.wait_for(session.commit(), timeout=6.0)
            except Exception as exc:
                try:
                    await session.rollback()
                except Exception:
                    pass
                exc_type = type(exc).__name__
                err_msg = str(exc) or exc_type
                lower_err = (err_msg + " " + exc_type).lower()
                is_transient = (
                    isinstance(exc, (TimeoutError, asyncio.TimeoutError, asyncio.CancelledError, ConnectionResetError, OSError))
                    or any(w in lower_err for w in (
                        "10054", "forcibly closed", "connection reset", "broken pipe", "cancelled",
                        "timeout", "time out", "connection was closed", "authentication timed out",
                        "terminating connection", "server closed the connection", "operationalerror",
                        "cannot connect", "getaddrinfo failed"
                    ))
                )
                if is_transient:
                    logger.debug(f"[Database] Transient connection drop/timeout in context: {err_msg}")
                else:
                    logger.warning(f"[Database] Session error in context: {err_msg}")
    except Exception as outer_exc:
        if not session_yielded:
            yield None
        outer_type = type(outer_exc).__name__
        err_msg = str(outer_exc) or outer_type
        lower_err = (err_msg + " " + outer_type).lower()
        is_transient = (
            isinstance(outer_exc, (TimeoutError, asyncio.TimeoutError, asyncio.CancelledError, ConnectionResetError, OSError))
            or any(w in lower_err for w in (
                "10054", "forcibly closed", "connection reset", "broken pipe", "cancelled",
                "timeout", "time out", "connection was closed", "authentication timed out",
                "terminating connection", "server closed the connection", "operationalerror",
                "cannot connect", "getaddrinfo failed"
            ))
        )
        if is_transient:
            logger.debug(f"[Database] Transient connection reset opening session: {err_msg}")
        else:
            logger.warning(f"[Database] Error in safe_db_context: {err_msg}")
