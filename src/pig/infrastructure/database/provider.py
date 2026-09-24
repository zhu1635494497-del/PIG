from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import stat
from typing import Iterator

from pig.application.errors import ApplicationError
from pig.infrastructure.database.engine import create_project_engine, session_factory
from pig.infrastructure.database.migrations import upgrade_database
from pig.infrastructure.database.uow import SqlAlchemyUnitOfWork


class SqlAlchemyProjectDatabase:
    """Open and close a short-lived engine for a single Project database action."""

    def migrate(self, database_path: Path) -> None:
        database_path.parent.mkdir(parents=False, exist_ok=True)
        upgrade_database(database_path)

    @contextmanager
    def unit_of_work(self, database_path: Path) -> Iterator[SqlAlchemyUnitOfWork]:
        try:
            database_stat = database_path.lstat()
        except FileNotFoundError as exc:
            raise ApplicationError(
                code="PROJECT_DATABASE_NOT_FOUND",
                message="project database does not exist",
                details={"path": str(database_path)},
            ) from exc
        if database_path.is_symlink() or not stat.S_ISREG(database_stat.st_mode):
            raise ApplicationError(
                code="UNSAFE_PROJECT_DATABASE",
                message="project database must be a regular non-symlink file",
                details={"path": str(database_path)},
            )
        engine = create_project_engine(database_path)
        try:
            with SqlAlchemyUnitOfWork(session_factory(engine)) as uow:
                yield uow
        finally:
            engine.dispose()
