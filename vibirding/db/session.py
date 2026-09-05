"""SQLAlchemy engine and session construction.

Transaction ownership stays with callers: repositories only add/query rows,
while `Log` or a later service chooses the transaction boundary.
"""

from __future__ import annotations

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from .. import config

SessionFactory = sessionmaker[Session]


class DatabaseConfigError(RuntimeError):
    """Raised when PostgreSQL configuration is missing."""


def build_engine(database_url: str | None = None) -> Engine:
    """Build a synchronous PostgreSQL engine from an explicit URL or `.env`."""
    url = database_url or config.load_database_url()
    if not url:
        raise DatabaseConfigError(
            "DATABASE_URL 未设置：请复制 .env.example 为 .env，并配置本地 PostgreSQL。"
        )
    return create_engine(url, pool_pre_ping=True)


def build_session_factory(engine: Engine | None = None) -> SessionFactory:
    """Return an injectable SQLAlchemy session factory."""
    return sessionmaker(
        bind=engine or build_engine(),
        class_=Session,
        expire_on_commit=False,
    )
