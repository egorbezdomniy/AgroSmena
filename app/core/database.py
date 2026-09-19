from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import DATABASE_PATH, sqlite_url
from app.models import Base
from app.core.migrations import upgrade_database
from app.repositories import sync_repository  # Register local deletion tracking.


class Database:
    """Owns the SQLAlchemy engine and creates the SQLite schema."""

    def __init__(self, path: Path = DATABASE_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.engine: Engine = create_engine(sqlite_url(path), future=True)
        event.listen(self.engine, "connect", self._enable_foreign_keys)
        self.session_factory = sessionmaker(
            bind=self.engine,
            class_=Session,
            expire_on_commit=False,
        )

    @staticmethod
    def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
        dbapi_connection.create_function(
            "casefold", 1, lambda value: value.casefold() if value is not None else ""
        )

    def create_tables(self) -> None:
        upgrade_database(self.engine)

    def dispose(self) -> None:
        self.engine.dispose()
