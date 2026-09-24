from __future__ import annotations

from types import TracebackType
from typing import Optional, Type

from sqlalchemy.orm import Session, sessionmaker

from pig.infrastructure.database.repositories import (
    SqlAlchemyCatalogRepository,
    SqlAlchemyProcessingRepository,
    SqlAlchemyProjectRepository,
)
from pig.infrastructure.database.workbench_repositories import (
    SqlAlchemyImportRepository,
    SqlAlchemyRecoveryRepository,
    SqlAlchemyWorkspaceRepository,
)


class SqlAlchemyUnitOfWork:
    """Explicit transaction boundary for one Project database."""

    def __init__(self, factory: sessionmaker[Session]) -> None:
        self._factory = factory
        self.session: Optional[Session] = None

    def __enter__(self) -> "SqlAlchemyUnitOfWork":
        self.session = self._factory()
        self.projects = SqlAlchemyProjectRepository(self.session)
        self.imports = SqlAlchemyImportRepository(self.session)
        self.workspace = SqlAlchemyWorkspaceRepository(self.session)
        self.catalog = SqlAlchemyCatalogRepository(self.session)
        self.processing = SqlAlchemyProcessingRepository(self.session)
        self.recovery = SqlAlchemyRecoveryRepository(self.session)
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        traceback: Optional[TracebackType],
    ) -> None:
        if self.session is None:
            return
        try:
            if exc_type is not None or self.session.in_transaction():
                self.session.rollback()
        finally:
            self.session.close()
            self.session = None

    def commit(self) -> None:
        if self.session is None:
            raise RuntimeError("unit of work has not been entered")
        self.session.commit()

    def rollback(self) -> None:
        if self.session is None:
            raise RuntimeError("unit of work has not been entered")
        self.session.rollback()
