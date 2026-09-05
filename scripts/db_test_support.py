"""PostgreSQL schema isolation helpers for offline checks and evals."""

from __future__ import annotations

import atexit
import uuid
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import Engine
from sqlalchemy.schema import CreateSchema, DropSchema
from sqlalchemy.orm import Session, sessionmaker

from vibirding.db.models import Base
from vibirding.db.session import build_engine, build_session_factory
from vibirding.memory.log import Log

_OPEN_CONTEXTS = []


@contextmanager
def temporary_schema(prefix: str = "test") -> Iterator[sessionmaker[Session]]:
    """Create one isolated PostgreSQL schema and remove it on exit."""
    schema = f"{prefix}_{uuid.uuid4().hex}"
    admin_engine = build_engine()
    test_engine: Engine | None = None
    try:
        with admin_engine.begin() as connection:
            connection.execute(CreateSchema(schema))
        test_engine = admin_engine.execution_options(
            schema_translate_map={None: schema}
        )
        Base.metadata.create_all(test_engine)
        yield build_session_factory(test_engine)
    finally:
        if test_engine is not None:
            test_engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True, if_exists=True))
        admin_engine.dispose()


def new_test_log(prefix: str = "test") -> Log:
    """Return an isolated Log kept alive until process exit."""
    context = temporary_schema(prefix)
    factory = context.__enter__()
    _OPEN_CONTEXTS.append(context)
    return Log(factory)


def _cleanup() -> None:
    while _OPEN_CONTEXTS:
        _OPEN_CONTEXTS.pop().__exit__(None, None, None)


atexit.register(_cleanup)
