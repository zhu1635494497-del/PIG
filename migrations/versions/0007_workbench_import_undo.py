"""workbench named project layout and top-level import undo

Revision ID: 0007_workbench_import_undo
Revises: 0006_working_versions
Create Date: 2026-09-23
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0007_workbench_import_undo"
down_revision: Union[str, None] = "0006_working_versions"
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
    'IMPORT_ITEM_UNDO_REQUESTED', 'IMPORT_ITEM_UNDO_COMPLETED',
    'IMPORT_ITEM_UNDO_FAILED', 'WORKSPACE_ITEM_ADDED', 'WORKSPACE_ITEM_MOVED',
    'WORKSPACE_ITEM_DELETED', 'WORKSPACE_ITEM_RESTORED',
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
    'IMPORT_ITEM_NOT_UNDOABLE', 'IMPORT_ITEM_UNDO_FAILED',
    'HANDLER_FAILURE', 'INTERNAL_ERROR',
)


def _enum(values, name):
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=True)


def _drop_workspace_placement_triggers() -> None:
    for trigger_name in (
        "trg_workspace_placement_parent_insert",
        "trg_workspace_placement_parent_update",
        "trg_workspace_placement_cycle_update",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS {trigger_name}")


def _create_workspace_placement_triggers() -> None:
    op.execute("""
        CREATE TRIGGER trg_workspace_placement_parent_insert
        BEFORE INSERT ON workspace_placements
        WHEN NEW.parent_workspace_item_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM workspace_items parent
              WHERE parent.id = NEW.parent_workspace_item_id
                AND parent.project_id = NEW.project_id
                AND parent.item_kind IN ('FOLDER', 'CONTAINER_VIEW')
                AND parent.lifecycle_status = 'ACTIVE'
          )
        BEGIN
            SELECT RAISE(ABORT, 'workspace parent must be an active folder or container view');
        END
    """)
    op.execute("""
        CREATE TRIGGER trg_workspace_placement_parent_update
        BEFORE UPDATE OF parent_workspace_item_id, project_id
        ON workspace_placements
        WHEN NEW.parent_workspace_item_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM workspace_items parent
              WHERE parent.id = NEW.parent_workspace_item_id
                AND parent.project_id = NEW.project_id
                AND parent.item_kind IN ('FOLDER', 'CONTAINER_VIEW')
                AND parent.lifecycle_status = 'ACTIVE'
          )
        BEGIN
            SELECT RAISE(ABORT, 'workspace parent must be an active folder or container view');
        END
    """)
    op.execute("""
        CREATE TRIGGER trg_workspace_placement_cycle_update
        BEFORE UPDATE OF parent_workspace_item_id ON workspace_placements
        WHEN NEW.parent_workspace_item_id IS NOT NULL
          AND EXISTS (
              WITH RECURSIVE subtree(id) AS (
                  SELECT NEW.workspace_item_id
                  UNION ALL
                  SELECT child.workspace_item_id
                  FROM workspace_placements child
                  JOIN subtree parent
                    ON child.parent_workspace_item_id = parent.id
              )
              SELECT 1 FROM subtree WHERE id = NEW.parent_workspace_item_id
          )
        BEGIN
            SELECT RAISE(ABORT, 'workspace placement cycle');
        END
    """)


def _create_original_snapshot_trigger() -> None:
    op.execute("""
        CREATE TRIGGER trg_original_snapshots_identity_immutable
        BEFORE UPDATE OF project_id, import_session_id, input_kind,
                         original_display_name, external_locator_at_import,
                         created_at ON original_snapshots
        BEGIN
            SELECT RAISE(ABORT, 'original snapshot identity is immutable');
        END
    """)


def _create_original_artifact_triggers() -> None:
    op.execute("""
        CREATE TRIGGER trg_original_artifacts_bytes_immutable
        BEFORE UPDATE OF project_id, snapshot_id, storage_key,
                         size, sha256, observed_modified_at, created_at
        ON original_artifacts
        BEGIN
            SELECT RAISE(ABORT, 'original artifact bytes and identity are immutable');
        END
    """)
    op.execute("""
        CREATE TRIGGER trg_original_artifact_origin_set_once
        BEFORE UPDATE OF source_node_id ON original_artifacts
        WHEN OLD.source_node_id IS NOT NULL
          AND OLD.source_node_id IS NOT NEW.source_node_id
        BEGIN
            SELECT RAISE(ABORT, 'original artifact source node is immutable once assigned');
        END
    """)


def _create_source_trigger() -> None:
    op.execute("""
        CREATE TRIGGER trg_sources_identity_immutable
        BEFORE UPDATE OF project_id, snapshot_id, kind, display_name, created_at
        ON sources
        WHEN OLD.project_id IS NOT NEW.project_id
          OR OLD.snapshot_id IS NOT NEW.snapshot_id
          OR OLD.kind IS NOT NEW.kind
          OR OLD.display_name IS NOT NEW.display_name
          OR OLD.created_at IS NOT NEW.created_at
        BEGIN
            SELECT RAISE(ABORT, 'source identity is immutable');
        END
    """)


def _create_workspace_item_trigger() -> None:
    op.execute("""
        CREATE TRIGGER trg_workspace_item_origin_immutable
        BEFORE UPDATE OF project_id, origin_source_node_id ON workspace_items
        WHEN OLD.project_id IS NOT NEW.project_id
          OR OLD.origin_source_node_id IS NOT NEW.origin_source_node_id
        BEGIN
            SELECT RAISE(ABORT, 'workspace item origin is immutable');
        END
    """)


def upgrade() -> None:
    with op.batch_alter_table("original_snapshots", schema=None) as batch_op:
        batch_op.alter_column(
            "status",
            existing_type=sa.String(length=11),
            type_=_enum(
                ('COPYING', 'VERIFYING', 'READY', 'FAILED', 'INTERRUPTED',
                 'MISSING', 'MISMATCH', 'UNREADABLE', 'PURGED'),
                "original_snapshot_status",
            ),
            existing_nullable=False,
        )
    _create_original_snapshot_trigger()
    with op.batch_alter_table("original_artifacts", schema=None) as batch_op:
        batch_op.alter_column(
            "integrity_status",
            existing_type=sa.String(length=10),
            type_=_enum(
                ('UNVERIFIED', 'VERIFYING', 'VERIFIED', 'MISSING', 'MISMATCH',
                 'UNREADABLE', 'PURGED'),
                "original_artifact_integrity_status",
            ),
            existing_nullable=False,
        )
    _create_original_artifact_triggers()
    with op.batch_alter_table("sources", schema=None) as batch_op:
        batch_op.alter_column(
            "status",
            existing_type=sa.String(length=10),
            type_=_enum(
                ('REGISTERED', 'VERIFYING', 'AVAILABLE', 'MISSING', 'CHANGED',
                 'UNREADABLE', 'PURGED'),
                "source_status",
            ),
            existing_nullable=False,
        )
    _create_source_trigger()
    _drop_workspace_placement_triggers()
    with op.batch_alter_table("workspace_items", schema=None) as batch_op:
        batch_op.drop_constraint(
            op.f("ck_workspace_items_deleted_at_matches_lifecycle"),
            type_="check",
        )
        batch_op.alter_column(
            "lifecycle_status",
            existing_type=sa.String(length=7),
            type_=_enum(('ACTIVE', 'DELETED', 'PURGED'), "workspace_item_lifecycle_status"),
            existing_nullable=False,
        )
        batch_op.create_check_constraint(
            "deleted_at_matches_lifecycle",
            "(lifecycle_status = 'ACTIVE' AND deleted_at IS NULL) OR "
            "(lifecycle_status IN ('DELETED', 'PURGED') AND deleted_at IS NOT NULL)",
        )
    _create_workspace_item_trigger()
    _create_workspace_placement_triggers()
    op.execute("DROP TRIGGER IF EXISTS trg_processing_events_append_only_update")
    op.execute("DROP TRIGGER IF EXISTS trg_processing_events_append_only_delete")
    with op.batch_alter_table("processing_events", schema=None) as batch_op:
        batch_op.alter_column(
            "event_type",
            existing_type=sa.String(length=35),
            type_=_enum(_EVENT_TYPES, "processing_event_type"),
            existing_nullable=False,
        )
        batch_op.alter_column(
            "error_code",
            existing_type=sa.String(length=37),
            type_=_enum(_ERROR_CODES, "processing_event_error_code"),
            existing_nullable=True,
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
    purged_count = sum(
        connection.execute(sa.text(statement)).scalar_one()
        for statement in (
            "SELECT COUNT(*) FROM original_snapshots WHERE status = 'PURGED'",
            "SELECT COUNT(*) FROM original_artifacts WHERE integrity_status = 'PURGED'",
            "SELECT COUNT(*) FROM sources WHERE status = 'PURGED'",
            "SELECT COUNT(*) FROM workspace_items WHERE lifecycle_status = 'PURGED'",
            "SELECT COUNT(*) FROM processing_events "
            "WHERE event_type IN ('IMPORT_ITEM_UNDO_REQUESTED', "
            "'IMPORT_ITEM_UNDO_COMPLETED', 'IMPORT_ITEM_UNDO_FAILED') "
            "OR error_code IN ('IMPORT_ITEM_NOT_UNDOABLE', "
            "'IMPORT_ITEM_UNDO_FAILED')",
        )
    )
    if purged_count:
        raise RuntimeError(
            "downgrade is disabled because it would discard import-undo facts"
        )

    previous_event_types = tuple(
        value
        for value in _EVENT_TYPES
        if value
        not in {
            "IMPORT_ITEM_UNDO_REQUESTED",
            "IMPORT_ITEM_UNDO_COMPLETED",
            "IMPORT_ITEM_UNDO_FAILED",
        }
    )
    previous_error_codes = tuple(
        value
        for value in _ERROR_CODES
        if value
        not in {"IMPORT_ITEM_NOT_UNDOABLE", "IMPORT_ITEM_UNDO_FAILED"}
    )

    op.execute("DROP TRIGGER IF EXISTS trg_processing_events_append_only_update")
    op.execute("DROP TRIGGER IF EXISTS trg_processing_events_append_only_delete")
    with op.batch_alter_table("processing_events", schema=None) as batch_op:
        batch_op.alter_column(
            "event_type",
            existing_type=sa.String(length=35),
            type_=_enum(previous_event_types, "processing_event_type"),
            existing_nullable=False,
        )
        batch_op.alter_column(
            "error_code",
            existing_type=sa.String(length=37),
            type_=_enum(previous_error_codes, "processing_event_error_code"),
            existing_nullable=True,
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

    _drop_workspace_placement_triggers()
    with op.batch_alter_table("workspace_items", schema=None) as batch_op:
        batch_op.drop_constraint(
            op.f("ck_workspace_items_deleted_at_matches_lifecycle"),
            type_="check",
        )
        batch_op.alter_column(
            "lifecycle_status",
            existing_type=sa.String(length=7),
            type_=_enum(
                ("ACTIVE", "DELETED"),
                "workspace_item_lifecycle_status",
            ),
            existing_nullable=False,
        )
        batch_op.create_check_constraint(
            "deleted_at_matches_lifecycle",
            "(lifecycle_status = 'ACTIVE' AND deleted_at IS NULL) OR "
            "(lifecycle_status = 'DELETED' AND deleted_at IS NOT NULL)",
        )
    _create_workspace_item_trigger()
    _create_workspace_placement_triggers()
    with op.batch_alter_table("sources", schema=None) as batch_op:
        batch_op.alter_column(
            "status",
            existing_type=sa.String(length=10),
            type_=_enum(
                ('REGISTERED', 'VERIFYING', 'AVAILABLE', 'MISSING', 'CHANGED',
                 'UNREADABLE'),
                "source_status",
            ),
            existing_nullable=False,
        )
    _create_source_trigger()
    with op.batch_alter_table("original_artifacts", schema=None) as batch_op:
        batch_op.alter_column(
            "integrity_status",
            existing_type=sa.String(length=10),
            type_=_enum(
                ('UNVERIFIED', 'VERIFYING', 'VERIFIED', 'MISSING', 'MISMATCH',
                 'UNREADABLE'),
                "original_artifact_integrity_status",
            ),
            existing_nullable=False,
        )
    _create_original_artifact_triggers()
    with op.batch_alter_table("original_snapshots", schema=None) as batch_op:
        batch_op.alter_column(
            "status",
            existing_type=sa.String(length=11),
            type_=_enum(
                ('COPYING', 'VERIFYING', 'READY', 'FAILED', 'INTERRUPTED',
                 'MISSING', 'MISMATCH', 'UNREADABLE'),
                "original_snapshot_status",
            ),
            existing_nullable=False,
        )
    _create_original_snapshot_trigger()
