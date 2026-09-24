from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, event
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy import create_engine


def create_project_engine(database_path: Path) -> Engine:
    """Create an engine for one Project's SQLite database.

    Directory creation is intentionally left to the application/workspace boundary.
    """

    resolved_path = database_path.resolve(strict=False)
    url = URL.create("sqlite+pysqlite", database=str(resolved_path))
    engine = create_engine(url, future=True)

    @event.listens_for(engine, "connect")
    def _configure_sqlite(dbapi_connection: object, connection_record: object) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.execute("PRAGMA journal_mode=WAL")
        finally:
            cursor.close()

    return engine


def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
