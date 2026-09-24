from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import Engine

from pig.infrastructure.database.engine import create_project_engine, session_factory
from pig.infrastructure.database.migrations import upgrade_database
from pig.infrastructure.database.uow import SqlAlchemyUnitOfWork


HISTORICAL_APPLICATION_TESTS = {
    "test_repositories.py",
    "test_schema_constraints.py",
    "test_milestone3_project_source_flow.py",
    "test_milestone4_processing.py",
    "test_milestone5_recursive_processing.py",
    "test_milestone6_email_processing.py",
    "test_milestone7_archive_processing.py",
    "test_milestone8_manifest_search.py",
    "test_milestone9_desktop_actions.py",
    "test_milestone10_recovery.py",
    "test_packaged_flow_acceptance.py",
    "test_main_window.py",
}


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Quarantine evidence-era tests after the Workbench reset."""

    historical = pytest.mark.skip(
        reason=(
            "historical evidence-era contract was superseded by ADR-010; "
            "replacement coverage is added by Workbench milestones"
        )
    )
    for item in items:
        path = Path(str(item.path))
        if path.name in HISTORICAL_APPLICATION_TESTS:
            item.add_marker(historical)


@pytest.fixture
def database_path(tmp_path: Path) -> Path:
    path = tmp_path / "project.sqlite"
    upgrade_database(path)
    return path


@pytest.fixture
def engine(database_path: Path) -> Engine:
    value = create_project_engine(database_path)
    yield value
    value.dispose()


@pytest.fixture
def uow_factory(engine: Engine):
    factory = session_factory(engine)
    return lambda: SqlAlchemyUnitOfWork(factory)
