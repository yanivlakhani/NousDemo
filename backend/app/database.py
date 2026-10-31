from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.settings import settings


class Base(DeclarativeBase):
    pass


def normalise_database_url(url: str) -> str:
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url.removeprefix("postgres://")
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url.removeprefix("postgresql://")
    return url


@lru_cache
def get_engine() -> Engine:
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is not configured")
    return create_engine(
        normalise_database_url(settings.database_url),
        # Supabase's transaction-mode pooler can hand a connection to a
        # different backend between transactions. Server-side prepared
        # statement names are therefore unsafe and can collide across Modal
        # workers (DuplicatePreparedStatement). Keep psycopg in unnamed mode.
        connect_args={"prepare_threshold": None},
        pool_pre_ping=True,
        # The UI starts with four independent read requests. FastAPI runs the
        # synchronous DB handlers in its worker pool, so keep enough checked-in
        # connections to serve that burst without QueuePool wait time.
        pool_size=5,
        max_overflow=2,
        # Modal keeps one demo container warm. Retain its healthy Supabase
        # connections rather than forcing a fresh TLS/database handshake every
        # five minutes; pre-ping still replaces a connection closed upstream.
        pool_recycle=1800,
        pool_use_lifo=True,
    )


@lru_cache
def get_read_engine() -> Engine:
    """Share the main pool while avoiding a transaction round trip for pure reads."""
    return get_engine().execution_options(isolation_level="AUTOCOMMIT")


@contextmanager
def session_scope() -> Iterator[Session]:
    factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@contextmanager
def read_session_scope() -> Iterator[Session]:
    """Open a non-flushing session for latency-sensitive, side-effect-free reads."""
    factory = sessionmaker(bind=get_read_engine(), expire_on_commit=False, autoflush=False)
    session = factory()
    try:
        yield session
        if session.new or session.dirty or session.deleted:
            raise RuntimeError("read_session_scope cannot persist changes")
    finally:
        session.close()
