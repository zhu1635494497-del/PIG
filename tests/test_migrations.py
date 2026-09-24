from __future__ import annotations

from pathlib import Path

from alembic import command
from sqlalchemy import create_engine, inspect, text

from pig.infrastructure.database.migrations import (
    alembic_config,
    downgrade_database,
    upgrade_database,
)


EXPECTED_TABLES = {
    "alembic_version",
    "projects",
    "sources",
    "source_roots",
    "source_entry_locators",
    "nodes",
    "artifacts",
    "node_relationships",
    "node_lineage",
    "node_metadata",
    "processing_jobs",
    "processing_attempts",
    "processing_events",
    "import_sessions",
    "import_session_items",
    "original_snapshots",
    "original_artifacts",
    "original_snapshot_entries",
    "workspace_items",
    "workspace_placements",
    "working_artifacts",
    "working_revisions",
    "recovery_runs",
    "recovery_items",
}


def test_upgrade_creates_the_complete_initial_schema(database_path: Path) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{database_path.as_posix()}")
    schema = inspect(engine)
    assert set(schema.get_table_names()) == EXPECTED_TABLES
    locator_columns = {
        column["name"] for column in schema.get_columns("source_entry_locators")
    }
    attempt_columns = {
        column["name"] for column in schema.get_columns("processing_attempts")
    }
    recovery_item_columns = {
        column["name"] for column in schema.get_columns("recovery_items")
    }
    assert {"member_ordinal", "expected_name", "member_role"} <= locator_columns
    assert "zip_member_ordinal" not in locator_columns
    assert {"backend_name", "backend_version", "backend_sha256"} <= attempt_columns
    assert {"storage_key", "recovery_storage_key", "size", "sha256"} <= (
        recovery_item_columns
    )

    with engine.connect() as connection:
        revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
        triggers = set(
            connection.scalars(
                text("SELECT name FROM sqlite_master WHERE type = 'trigger'")
            )
        )

    assert revision == "0008_workbench_recovery"
    project_columns = {
        column["name"] for column in schema.get_columns("projects")
    }
    import_columns = {
        column["name"] for column in schema.get_columns("import_sessions")
    }
    assert "workspace_revision" in project_columns
    assert {
        "target_workspace_parent_id",
        "expected_workspace_revision",
    } <= import_columns
    assert "trg_processing_events_append_only_update" in triggers
    assert "trg_processing_events_append_only_delete" in triggers
    assert "trg_original_artifacts_bytes_immutable" in triggers
    assert "trg_original_snapshot_entries_identity_immutable" in triggers
    assert "trg_workspace_item_origin_immutable" in triggers
    assert "trg_workspace_placement_cycle_update" in triggers
    assert "trg_source_entry_locators_immutable_update" in triggers
    assert "trg_source_entry_locators_immutable_delete" in triggers


def test_migration_matches_current_sqlalchemy_metadata(database_path: Path) -> None:
    command.check(alembic_config(database_path))


def test_application_engine_enables_sqlite_integrity_pragmas(engine) -> None:
    with engine.connect() as connection:
        assert connection.scalar(text("PRAGMA foreign_keys")) == 1
        assert connection.scalar(text("PRAGMA journal_mode")) == "wal"
        assert connection.scalar(text("PRAGMA busy_timeout")) == 5000


def test_downgrade_returns_database_to_base(tmp_path: Path) -> None:
    database_path = tmp_path / "downgrade.sqlite"
    upgrade_database(database_path)
    downgrade_database(database_path)

    engine = create_engine(f"sqlite+pysqlite:///{database_path.as_posix()}")
    assert inspect(engine).get_table_names() == ["alembic_version"]
