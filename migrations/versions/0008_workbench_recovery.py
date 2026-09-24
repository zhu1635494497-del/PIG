"""workbench recovery runs and items

Revision ID: 0008_workbench_recovery
Revises: 0007_workbench_import_undo
Create Date: 2026-09-24
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pig.infrastructure.database.types import UTCDateTime


revision: str = "0008_workbench_recovery"
down_revision: Union[str, None] = "0007_workbench_import_undo"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _enum(values: tuple[str, ...], name: str) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=True)


def upgrade() -> None:
    op.create_table(
        "recovery_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column(
            "status",
            _enum(
                (
                    "DETECTED",
                    "AWAITING_CONFIRMATION",
                    "RUNNING",
                    "SUCCESS",
                    "PARTIAL_SUCCESS",
                    "FAILED",
                ),
                "recovery_run_status",
            ),
            nullable=False,
        ),
        sa.Column("actor", sa.String(length=255), nullable=False),
        sa.Column("correlation_id", sa.String(length=36), nullable=False),
        sa.Column("detected_count", sa.Integer(), nullable=False),
        sa.Column("recovered_count", sa.Integer(), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("started_at", UTCDateTime(), nullable=True),
        sa.Column("finished_at", UTCDateTime(), nullable=True),
        sa.CheckConstraint("detected_count >= 0", name="detected_count_nonnegative"),
        sa.CheckConstraint("recovered_count >= 0", name="recovered_count_nonnegative"),
        sa.CheckConstraint("failed_count >= 0", name="failed_count_nonnegative"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "project_id", name="uq_recovery_runs_id_project"),
    )
    op.create_index(
        "ix_recovery_runs_project_created",
        "recovery_runs",
        ["project_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "recovery_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("recovery_run_id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column(
            "kind",
            _enum(
                (
                    "SNAPSHOT_STAGING",
                    "MATERIALIZATION_STAGING",
                    "VERSION_STAGING",
                    "IMPORT_UNDO_STAGING",
                    "INSPECTION_CACHE",
                    "UNREGISTERED_ORIGINAL",
                    "UNREGISTERED_WORKING",
                    "UNREGISTERED_VERSION",
                    "UNKNOWN_STAGING",
                    "OPERATION_MANIFEST",
                ),
                "recovery_item_kind",
            ),
            nullable=False,
        ),
        sa.Column(
            "action",
            _enum(
                (
                    "RESTORE",
                    "QUARANTINE",
                    "REMOVE_REPRODUCIBLE",
                    "REMOVE_MANIFEST",
                    "UNCHANGED",
                ),
                "recovery_action",
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            _enum(
                (
                    "DISCOVERED",
                    "PLANNED",
                    "RESTORED",
                    "QUARANTINED",
                    "REMOVED_REPRODUCIBLE",
                    "UNCHANGED",
                    "FAILED",
                ),
                "recovery_item_status",
            ),
            nullable=False,
        ),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("operation_id", sa.String(length=128), nullable=True),
        sa.Column("size", sa.Integer(), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("recovery_storage_key", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=True),
        sa.CheckConstraint(
            "length(trim(storage_key)) > 0", name="storage_key_not_blank"
        ),
        sa.CheckConstraint("size IS NULL OR size >= 0", name="size_nonnegative"),
        sa.CheckConstraint(
            "sha256 IS NULL OR "
            "(length(sha256) = 64 AND sha256 NOT GLOB '*[^0-9a-f]*')",
            name="sha256_canonical",
        ),
        sa.CheckConstraint(
            "substr(storage_key, 1, 1) <> '/' "
            "AND instr(storage_key, '\\') = 0 "
            "AND instr('/' || storage_key || '/', '/../') = 0",
            name="storage_key_project_relative",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["recovery_run_id", "project_id"],
            ["recovery_runs.id", "recovery_runs.project_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "project_id", name="uq_recovery_items_id_project"),
    )
    op.create_index(
        "ix_recovery_items_run_status",
        "recovery_items",
        ["recovery_run_id", "status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_recovery_items_run_status", table_name="recovery_items")
    op.drop_table("recovery_items")
    op.drop_index("ix_recovery_runs_project_created", table_name="recovery_runs")
    op.drop_table("recovery_runs")
