"""workbench current and previous working versions

Revision ID: 0006_working_versions
Revises: 0005_workspace_actions
Create Date: 2026-09-23
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0006_working_versions"
down_revision: Union[str, None] = "0005_workspace_actions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_EVENT_TYPES = (
    'PROJECT_CREATED', 'PROJECT_STATUS_CHANGED', 'SOURCE_REGISTERED',
    'SOURCE_VERIFICATION_STARTED', 'SOURCE_VERIFIED', 'SOURCE_MISSING_DETECTED',
    'SOURCE_CHANGED_DETECTED', 'SOURCE_UNREADABLE_DETECTED', 'NODE_DISCOVERED',
    'NODE_FORMAT_DETECTED', 'NODE_QUEUED', 'NODE_PROCESSING_STARTED',
    'CONTAINER_OPENED', 'CHILD_DISCOVERED', 'CHILD_EXTRACTED',
    'RELATIONSHIP_CREATED', 'LINEAGE_UPDATED', 'NODE_PROCESSING_FINISHED',
    'NODE_PROCESSING_BLOCKED', 'NODE_PROCESSING_FAILED', 'JOB_CREATED',
    'JOB_STARTED', 'JOB_INTERRUPTED', 'JOB_FINISHED', 'ATTEMPT_QUEUED',
    'ATTEMPT_STARTED', 'ATTEMPT_FINISHED', 'ATTEMPT_FAILED',
    'ATTEMPT_INTERRUPTED', 'ATTEMPT_CANCELLED', 'ARTIFACT_REGISTERED',
    'ARTIFACT_VERIFIED', 'ARTIFACT_INTEGRITY_FAILED',
    'ARTIFACT_VERIFICATION_INTERRUPTED', 'FILE_OPEN_REQUESTED', 'FILE_OPENED',
    'FILE_OPEN_DENIED', 'FILE_OPEN_FAILED', 'RECOVERY_STARTED',
    'RECOVERY_FINISHED', 'RECOVERY_FAILED', 'JOB_CANCELLED',
    'NODE_PROCESSING_INTERRUPTED', 'ORPHAN_QUARANTINED',
    'MANIFEST_EXPORT_REQUESTED', 'MANIFEST_EXPORTED', 'MANIFEST_EXPORT_FAILED',
    'LINEAGE_INTEGRITY_FAILED', 'LINEAGE_REBUILT', 'IMPORT_REQUESTED',
    'IMPORT_STARTED', 'IMPORT_FINISHED', 'IMPORT_FAILED', 'IMPORT_INTERRUPTED',
    'IMPORT_SNAPSHOT_CAPTURE_FINISHED', 'SNAPSHOT_COPY_STARTED',
    'SNAPSHOT_VERIFICATION_STARTED', 'SNAPSHOT_READY',
    'SNAPSHOT_INTEGRITY_FAILED', 'WORKING_FILE_MATERIALIZATION_STARTED',
    'WORKING_FILE_MATERIALIZED', 'WORKING_FILE_MATERIALIZATION_FAILED',
    'WORKING_FILE_MODIFIED', 'WORKING_FILE_MISSING', 'WORKING_FILE_UNREADABLE',
    'WORKING_FILE_RESTORED_CLEAN', 'WORKING_VERSION_CAPTURED',
    'WORKING_FILE_ROLLED_BACK', 'WORKSPACE_EXPORT_REQUESTED',
    'WORKSPACE_EXPORT_COMPLETED', 'WORKSPACE_EXPORT_FAILED',
    'WORKSPACE_ITEM_ADDED', 'WORKSPACE_ITEM_MOVED', 'WORKSPACE_ITEM_DELETED',
    'WORKSPACE_ITEM_RESTORED',
)

_ERROR_CODES = (
    'INPUT_NOT_FOUND', 'INPUT_UNREADABLE', 'INPUT_CHANGED_DURING_COPY',
    'INPUT_OVERLAPS_PROJECT', 'DUPLICATE_INPUT', 'UNSUPPORTED_INPUT_TYPE',
    'SNAPSHOT_PUBLISH_FAILED', 'MAX_IMPORT_ENTRY_COUNT_EXCEEDED',
    'MAX_IMPORT_TOTAL_SIZE_EXCEEDED', 'SOURCE_NOT_FOUND',
    'SOURCE_FINGERPRINT_MISMATCH', 'SOURCE_OUTSIDE_BOUNDARY', 'SYMLINK_BLOCKED',
    'PATH_TRAVERSAL_BLOCKED', 'ABSOLUTE_PATH_BLOCKED', 'DEVICE_PATH_BLOCKED',
    'INVALID_FILENAME', 'PASSWORD_REQUIRED', 'CORRUPTED_CONTAINER',
    'UNSUPPORTED_FORMAT', 'UNSUPPORTED_FEATURE', 'DEPENDENCY_UNAVAILABLE',
    'DEPENDENCY_VERSION_UNSUPPORTED', 'EXTERNAL_PROCESS_TIMEOUT',
    'EXTERNAL_PROCESS_OUTPUT_EXCEEDED', 'MANIFEST_SIZE_EXCEEDED',
    'MANIFEST_EXPORT_FAILED', 'MAX_DEPTH_EXCEEDED', 'MAX_NODE_COUNT_EXCEEDED',
    'MAX_ARCHIVE_ENTRIES_EXCEEDED', 'MAX_SINGLE_FILE_SIZE_EXCEEDED',
    'MAX_TOTAL_EXPANDED_SIZE_EXCEEDED', 'MAX_COMPRESSION_RATIO_EXCEEDED',
    'ARTIFACT_MISSING', 'ARTIFACT_UNREADABLE', 'ARTIFACT_HASH_MISMATCH',
    'OPEN_FORMAT_DENIED', 'OPEN_INTEGRITY_REQUIRED', 'OPEN_HANDOFF_FAILED',
    'RECOVERY_FAILED', 'WORKSPACE_INTEGRITY_FAILED',
    'WORKING_VERSION_NOT_FOUND', 'WORKING_VERSION_INTEGRITY_FAILED',
    'EXPORT_DESTINATION_INVALID', 'EXPORT_PATH_COLLISION', 'EXPORT_FAILED',
    'HANDLER_FAILURE', 'INTERNAL_ERROR',
)


def upgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_processing_events_append_only_update")
    op.execute("DROP TRIGGER IF EXISTS trg_processing_events_append_only_delete")
    with op.batch_alter_table("processing_events", schema=None) as batch_op:
        batch_op.alter_column(
            "event_type",
            existing_type=sa.String(length=35),
            type_=sa.Enum(
                *_EVENT_TYPES,
                name="processing_event_type",
                native_enum=False,
                create_constraint=True,
            ),
            existing_nullable=False,
        )
        batch_op.alter_column(
            "error_code",
            existing_type=sa.String(length=37),
            type_=sa.Enum(
                *_ERROR_CODES,
                name="processing_event_error_code",
                native_enum=False,
                create_constraint=True,
            ),
            existing_nullable=True,
        )
    op.create_table(
        "working_revisions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("working_artifact_id", sa.String(length=36), nullable=False),
        sa.Column(
            "role",
            sa.Enum(
                "CURRENT_CHECKPOINT",
                "PREVIOUS",
                name="working_revision_role",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("file_modified_at", sa.String(length=32), nullable=False),
        sa.Column("detected_at", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.String(length=32), nullable=False),
        sa.Column("updated_at", sa.String(length=32), nullable=False),
        sa.CheckConstraint("size >= 0", name="ck_working_revisions_size_nonnegative"),
        sa.CheckConstraint(
            "length(sha256) = 64 AND sha256 NOT GLOB '*[^0-9a-f]*'",
            name="ck_working_revisions_sha256_canonical",
        ),
        sa.CheckConstraint(
            "length(trim(storage_key)) > 0",
            name="ck_working_revisions_storage_key_not_blank",
        ),
        sa.CheckConstraint(
            "substr(storage_key, 1, 1) <> '/' "
            "AND instr(storage_key, '\\\\') = 0 "
            "AND instr('/' || storage_key || '/', '/../') = 0",
            name="ck_working_revisions_storage_key_project_relative",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["working_artifact_id", "project_id"],
            ["working_artifacts.id", "working_artifacts.project_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_working_revisions"),
        sa.UniqueConstraint(
            "id", "project_id", name="uq_working_revisions_id_project"
        ),
        sa.UniqueConstraint(
            "working_artifact_id",
            "role",
            name="uq_working_revisions_artifact_role",
        ),
        sa.UniqueConstraint(
            "project_id", "storage_key", name="uq_working_revisions_storage_key"
        ),
    )
    op.create_index(
        "ix_working_revisions_artifact",
        "working_revisions",
        ["working_artifact_id", "role"],
        unique=False,
    )
    op.execute("""
        CREATE TRIGGER trg_processing_events_append_only_update
        BEFORE UPDATE ON processing_events
        BEGIN
            SELECT RAISE(ABORT, 'processing events are append-only');
        END
    """)
    op.execute("""
        CREATE TRIGGER trg_processing_events_append_only_delete
        BEFORE DELETE ON processing_events
        BEGIN
            SELECT RAISE(ABORT, 'processing events are append-only');
        END
    """)


def downgrade() -> None:
    connection = op.get_bind()
    count = connection.execute(
        sa.text("SELECT COUNT(*) FROM working_revisions")
    ).scalar_one()
    if count:
        raise RuntimeError(
            "downgrade is disabled because it would discard Working version facts"
        )
    op.drop_index("ix_working_revisions_artifact", table_name="working_revisions")
    op.drop_table("working_revisions")
