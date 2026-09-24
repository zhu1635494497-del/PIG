from __future__ import annotations

from datetime import datetime, timezone

import pytest

from pig.application.contracts import CreateProjectRequest, LoadProjectRequest
from pig.application.errors import ApplicationError
from pig.bootstrap import create_local_application
from pig.domain.entities import Project
from pig.domain.enums import ProjectStatus
from pig.domain.model_version import WORKBENCH_MODEL_VERSION
from pig.infrastructure.database.engine import create_project_engine, session_factory
from pig.infrastructure.database.migrations import upgrade_database
from pig.infrastructure.database.uow import SqlAlchemyUnitOfWork


def test_new_project_uses_workbench_model_and_reloads(tmp_path) -> None:
    application = create_local_application(tmp_path)
    created = application.create_project(
        CreateProjectRequest(name="W1 Project", actor="tester")
    )

    loaded = application.load_project(
        LoadProjectRequest(database_path=created.database_path)
    )

    assert loaded.project.id == created.project_id
    assert loaded.project.model_version == WORKBENCH_MODEL_VERSION
    assert loaded.sources == ()
    assert [event.event_type.value for event in loaded.events] == [
        "PROJECT_CREATED"
    ]


def test_old_project_model_is_rejected_clearly(tmp_path) -> None:
    workspace = tmp_path / "legacy-project"
    workspace.mkdir()
    database_path = workspace / "project.sqlite"
    upgrade_database(database_path)
    now = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)
    engine = create_project_engine(database_path)
    try:
        with SqlAlchemyUnitOfWork(session_factory(engine)) as uow:
            uow.projects.add(
                Project(
                    id="legacy",
                    name="Legacy",
                    status=ProjectStatus.CREATED,
                    workspace_locator=workspace.as_uri(),
                    model_version="1",
                    created_at=now,
                    updated_at=now,
                )
            )
            uow.commit()
    finally:
        engine.dispose()

    application = create_local_application(tmp_path)
    with pytest.raises(ApplicationError) as error:
        application.load_project(LoadProjectRequest(database_path=database_path))

    assert error.value.code == "UNSUPPORTED_PROJECT_MODEL_VERSION"
    assert error.value.details["actual_model_version"] == "1"
    assert error.value.details["supported_model_version"] == WORKBENCH_MODEL_VERSION
