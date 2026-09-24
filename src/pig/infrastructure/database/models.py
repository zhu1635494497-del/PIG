from __future__ import annotations

from datetime import datetime
from typing import Any, Optional, Type

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Enum as SAEnum,
    Float,
    ForeignKeyConstraint,
    Index,
    Integer,
    JSON,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from pig.domain import enums
from pig.domain.enums import StringEnum
from pig.infrastructure.database.base import Base
from pig.infrastructure.database.types import UTCDateTime


def enum_type(enum_class: Type[StringEnum], name: str) -> SAEnum:
    return SAEnum(
        enum_class,
        name=name,
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        values_callable=lambda items: [item.value for item in items],
    )


class ProjectModel(Base):
    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint("singleton_key = 1", name="singleton_key_is_one"),
        CheckConstraint("length(trim(name)) > 0", name="name_not_blank"),
        CheckConstraint("workspace_revision >= 0", name="workspace_revision_nonnegative"),
        UniqueConstraint("singleton_key", name="uq_projects_singleton"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    singleton_key: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[enums.ProjectStatus] = mapped_column(
        enum_type(enums.ProjectStatus, "project_status"), nullable=False
    )
    workspace_locator: Mapped[str] = mapped_column(Text, nullable=False)
    model_version: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    workspace_revision: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )


class ImportSessionModel(Base):
    __tablename__ = "import_sessions"
    __table_args__ = (
        UniqueConstraint("id", "project_id", name="uq_import_sessions_id_project"),
        UniqueConstraint(
            "project_id",
            "correlation_id",
            name="uq_import_sessions_project_correlation",
        ),
        CheckConstraint(
            "requested_item_count >= 0", name="requested_item_count_nonnegative"
        ),
        CheckConstraint(
            "accepted_item_count >= 0", name="accepted_item_count_nonnegative"
        ),
        CheckConstraint(
            "failed_item_count >= 0", name="failed_item_count_nonnegative"
        ),
        CheckConstraint(
            "accepted_item_count + failed_item_count <= requested_item_count",
            name="result_counts_within_requested",
        ),
        CheckConstraint(
            "expected_workspace_revision IS NULL OR expected_workspace_revision >= 0",
            name="expected_workspace_revision_nonnegative",
        ),
        ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(
            ["target_workspace_parent_id", "project_id"],
            ["workspace_items.id", "workspace_items.project_id"],
            name="fk_import_sessions_target_workspace_parent_id_workspace_items",
            ondelete="RESTRICT",
            use_alter=True,
        ),
        Index("ix_import_sessions_project_status", "project_id", "status"),
        Index(
            "ix_import_sessions_workspace_target",
            "project_id",
            "target_workspace_parent_id",
        ),
        Index(
            "uq_import_sessions_one_active_project",
            "project_id",
            unique=True,
            sqlite_where=text(
                "status IN ('QUEUED', 'SNAPSHOTTING', 'INSPECTING')"
            ),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), nullable=False)
    status: Mapped[enums.ImportSessionStatus] = mapped_column(
        enum_type(enums.ImportSessionStatus, "import_session_status"), nullable=False
    )
    requested_item_count: Mapped[int] = mapped_column(Integer, nullable=False)
    accepted_item_count: Mapped[int] = mapped_column(Integer, nullable=False)
    failed_item_count: Mapped[int] = mapped_column(Integer, nullable=False)
    requested_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime())
    finished_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime())
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    policy_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    target_workspace_parent_id: Mapped[Optional[str]] = mapped_column(String(36))
    expected_workspace_revision: Mapped[Optional[int]] = mapped_column(Integer)


class ImportSessionItemModel(Base):
    __tablename__ = "import_session_items"
    __table_args__ = (
        UniqueConstraint("id", "project_id", name="uq_import_session_items_id_project"),
        UniqueConstraint(
            "import_session_id", "ordinal", name="uq_import_session_items_session_ordinal"
        ),
        CheckConstraint("ordinal >= 0", name="ordinal_nonnegative"),
        CheckConstraint("length(trim(input_locator)) > 0", name="input_locator_not_blank"),
        CheckConstraint(
            "(status = 'FAILED' AND error_code IS NOT NULL AND error_message IS NOT NULL) "
            "OR (status <> 'FAILED')",
            name="failed_item_has_error",
        ),
        ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(
            ["import_session_id", "project_id"],
            ["import_sessions.id", "import_sessions.project_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["snapshot_id", "project_id"],
            ["original_snapshots.id", "original_snapshots.project_id"],
            ondelete="RESTRICT",
        ),
        Index(
            "ix_import_session_items_session_status",
            "import_session_id",
            "status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), nullable=False)
    import_session_id: Mapped[str] = mapped_column(String(36), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    input_locator: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[enums.ImportItemStatus] = mapped_column(
        enum_type(enums.ImportItemStatus, "import_item_status"), nullable=False
    )
    snapshot_id: Mapped[Optional[str]] = mapped_column(String(36))
    error_code: Mapped[Optional[str]] = mapped_column(String(64))
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class OriginalSnapshotModel(Base):
    __tablename__ = "original_snapshots"
    __table_args__ = (
        UniqueConstraint("id", "project_id", name="uq_original_snapshots_id_project"),
        CheckConstraint(
            "length(trim(original_display_name)) > 0",
            name="original_display_name_not_blank",
        ),
        CheckConstraint(
            "length(trim(external_locator_at_import)) > 0",
            name="external_locator_at_import_not_blank",
        ),
        ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(
            ["import_session_id", "project_id"],
            ["import_sessions.id", "import_sessions.project_id"],
            ondelete="RESTRICT",
        ),
        Index("ix_original_snapshots_project_status", "project_id", "status"),
        Index(
            "ix_original_snapshots_import_session",
            "project_id",
            "import_session_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), nullable=False)
    import_session_id: Mapped[str] = mapped_column(String(36), nullable=False)
    input_kind: Mapped[enums.SourceKind] = mapped_column(
        enum_type(enums.SourceKind, "original_snapshot_input_kind"), nullable=False
    )
    original_display_name: Mapped[str] = mapped_column(String(512), nullable=False)
    external_locator_at_import: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[enums.OriginalSnapshotStatus] = mapped_column(
        enum_type(enums.OriginalSnapshotStatus, "original_snapshot_status"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    verified_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime())


class OriginalArtifactModel(Base):
    __tablename__ = "original_artifacts"
    __table_args__ = (
        UniqueConstraint("id", "project_id", name="uq_original_artifacts_id_project"),
        UniqueConstraint(
            "id",
            "project_id",
            "snapshot_id",
            name="uq_original_artifacts_id_project_snapshot",
        ),
        UniqueConstraint("project_id", "storage_key", name="uq_original_artifacts_storage_key"),
        CheckConstraint("size >= 0", name="size_nonnegative"),
        CheckConstraint(
            "length(sha256) = 64 AND sha256 NOT GLOB '*[^0-9a-f]*'",
            name="sha256_canonical",
        ),
        CheckConstraint("length(trim(storage_key)) > 0", name="storage_key_not_blank"),
        CheckConstraint("size IS NULL OR size >= 0", name="size_nonnegative"),
        CheckConstraint(
            "sha256 IS NULL OR "
            "(length(sha256) = 64 AND sha256 NOT GLOB '*[^0-9a-f]*')",
            name="sha256_canonical",
        ),
        CheckConstraint(
            "substr(storage_key, 1, 1) <> '/' "
            "AND instr(storage_key, '\\\\') = 0 "
            "AND instr('/' || storage_key || '/', '/../') = 0",
            name="storage_key_project_relative",
        ),
        ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(
            ["snapshot_id", "project_id"],
            ["original_snapshots.id", "original_snapshots.project_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["source_node_id", "project_id"],
            ["nodes.id", "nodes.project_id"],
            ondelete="RESTRICT",
        ),
        Index("ix_original_artifacts_snapshot", "project_id", "snapshot_id"),
        Index("ix_original_artifacts_sha256", "sha256"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), nullable=False)
    snapshot_id: Mapped[str] = mapped_column(String(36), nullable=False)
    source_node_id: Mapped[Optional[str]] = mapped_column(String(36))
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_modified_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime())
    integrity_status: Mapped[enums.ArtifactIntegrityStatus] = mapped_column(
        enum_type(enums.ArtifactIntegrityStatus, "original_artifact_integrity_status"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class OriginalSnapshotEntryModel(Base):
    __tablename__ = "original_snapshot_entries"
    __table_args__ = (
        UniqueConstraint(
            "id", "project_id", "snapshot_id",
            name="uq_original_snapshot_entries_identity",
        ),
        UniqueConstraint(
            "snapshot_id", "parent_entry_id", "ordinal",
            name="uq_original_snapshot_entries_sibling_ordinal",
        ),
        CheckConstraint("length(original_name) > 0", name="original_name_not_empty"),
        CheckConstraint("ordinal >= 0", name="ordinal_nonnegative"),
        CheckConstraint(
            "(kind = 'FILE' AND artifact_id IS NOT NULL) OR "
            "(kind = 'FOLDER' AND artifact_id IS NULL)",
            name="kind_matches_artifact",
        ),
        CheckConstraint(
            "parent_entry_id IS NULL OR parent_entry_id <> id",
            name="parent_not_self",
        ),
        ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(
            ["snapshot_id", "project_id"],
            ["original_snapshots.id", "original_snapshots.project_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["parent_entry_id", "project_id", "snapshot_id"],
            [
                "original_snapshot_entries.id",
                "original_snapshot_entries.project_id",
                "original_snapshot_entries.snapshot_id",
            ],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["artifact_id", "project_id", "snapshot_id"],
            [
                "original_artifacts.id",
                "original_artifacts.project_id",
                "original_artifacts.snapshot_id",
            ],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["source_node_id", "project_id"],
            ["nodes.id", "nodes.project_id"],
            ondelete="RESTRICT",
        ),
        Index(
            "ix_original_snapshot_entries_parent",
            "project_id",
            "snapshot_id",
            "parent_entry_id",
            "ordinal",
        ),
        Index(
            "uq_original_snapshot_entries_one_root",
            "snapshot_id",
            unique=True,
            sqlite_where=text("parent_entry_id IS NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), nullable=False)
    snapshot_id: Mapped[str] = mapped_column(String(36), nullable=False)
    parent_entry_id: Mapped[Optional[str]] = mapped_column(String(36))
    artifact_id: Mapped[Optional[str]] = mapped_column(String(36))
    source_node_id: Mapped[Optional[str]] = mapped_column(String(36))
    kind: Mapped[enums.OriginalSnapshotEntryKind] = mapped_column(
        enum_type(enums.OriginalSnapshotEntryKind, "original_snapshot_entry_kind"),
        nullable=False,
    )
    original_name: Mapped[str] = mapped_column(Text, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class WorkspaceItemModel(Base):
    __tablename__ = "workspace_items"
    __table_args__ = (
        UniqueConstraint("id", "project_id", name="uq_workspace_items_id_project"),
        CheckConstraint("length(trim(display_name)) > 0", name="display_name_not_blank"),
        CheckConstraint(
            "(lifecycle_status = 'ACTIVE' AND deleted_at IS NULL) OR "
            "(lifecycle_status IN ('DELETED', 'PURGED') AND deleted_at IS NOT NULL)",
            name="deleted_at_matches_lifecycle",
        ),
        ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(
            ["origin_source_node_id", "project_id"],
            ["nodes.id", "nodes.project_id"],
            ondelete="RESTRICT",
        ),
        Index(
            "ix_workspace_items_project_lifecycle",
            "project_id",
            "lifecycle_status",
        ),
        Index("ix_workspace_items_origin", "project_id", "origin_source_node_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), nullable=False)
    origin_source_node_id: Mapped[Optional[str]] = mapped_column(String(36))
    item_kind: Mapped[enums.WorkspaceItemKind] = mapped_column(
        enum_type(enums.WorkspaceItemKind, "workspace_item_kind"), nullable=False
    )
    display_name: Mapped[str] = mapped_column(String(512), nullable=False)
    lifecycle_status: Mapped[enums.WorkspaceItemLifecycleStatus] = mapped_column(
        enum_type(enums.WorkspaceItemLifecycleStatus, "workspace_item_lifecycle_status"),
        nullable=False,
    )
    materialization_status: Mapped[enums.WorkspaceMaterializationStatus] = mapped_column(
        enum_type(
            enums.WorkspaceMaterializationStatus,
            "workspace_materialization_status",
        ),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime())


class WorkspacePlacementModel(Base):
    __tablename__ = "workspace_placements"
    __table_args__ = (
        PrimaryKeyConstraint("workspace_item_id", name="pk_workspace_placements"),
        CheckConstraint("ordinal >= 0", name="ordinal_nonnegative"),
        CheckConstraint(
            "previous_ordinal IS NULL OR previous_ordinal >= 0",
            name="previous_ordinal_nonnegative",
        ),
        CheckConstraint(
            "parent_workspace_item_id IS NULL "
            "OR parent_workspace_item_id <> workspace_item_id",
            name="parent_not_self",
        ),
        CheckConstraint(
            "previous_parent_id IS NULL OR previous_parent_id <> workspace_item_id",
            name="previous_parent_not_self",
        ),
        ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(
            ["workspace_item_id", "project_id"],
            ["workspace_items.id", "workspace_items.project_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["parent_workspace_item_id", "project_id"],
            ["workspace_items.id", "workspace_items.project_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["previous_parent_id", "project_id"],
            ["workspace_items.id", "workspace_items.project_id"],
            ondelete="RESTRICT",
        ),
        Index(
            "ix_workspace_placements_parent_order",
            "project_id",
            "parent_workspace_item_id",
            "ordinal",
        ),
    )

    workspace_item_id: Mapped[str] = mapped_column(String(36), nullable=False)
    project_id: Mapped[str] = mapped_column(String(36), nullable=False)
    parent_workspace_item_id: Mapped[Optional[str]] = mapped_column(String(36))
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_parent_id: Mapped[Optional[str]] = mapped_column(String(36))
    previous_ordinal: Mapped[Optional[int]] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class WorkingArtifactModel(Base):
    __tablename__ = "working_artifacts"
    __table_args__ = (
        UniqueConstraint("id", "project_id", name="uq_working_artifacts_id_project"),
        UniqueConstraint("workspace_item_id", name="uq_working_artifacts_workspace_item"),
        UniqueConstraint("project_id", "storage_key", name="uq_working_artifacts_storage_key"),
        CheckConstraint("baseline_size >= 0", name="baseline_size_nonnegative"),
        CheckConstraint("current_size >= 0", name="current_size_nonnegative"),
        CheckConstraint(
            "length(baseline_sha256) = 64 "
            "AND baseline_sha256 NOT GLOB '*[^0-9a-f]*'",
            name="baseline_sha256_canonical",
        ),
        CheckConstraint(
            "length(current_sha256) = 64 "
            "AND current_sha256 NOT GLOB '*[^0-9a-f]*'",
            name="current_sha256_canonical",
        ),
        CheckConstraint("length(trim(storage_key)) > 0", name="storage_key_not_blank"),
        CheckConstraint(
            "substr(storage_key, 1, 1) <> '/' "
            "AND instr(storage_key, '\\\\') = 0 "
            "AND instr('/' || storage_key || '/', '/../') = 0",
            name="storage_key_project_relative",
        ),
        ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(
            ["workspace_item_id", "project_id"],
            ["workspace_items.id", "workspace_items.project_id"],
            ondelete="RESTRICT",
        ),
        Index("ix_working_artifacts_project_status", "project_id", "content_status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), nullable=False)
    workspace_item_id: Mapped[str] = mapped_column(String(36), nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    baseline_size: Mapped[int] = mapped_column(Integer, nullable=False)
    baseline_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    current_size: Mapped[int] = mapped_column(Integer, nullable=False)
    current_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    content_status: Mapped[enums.WorkingContentStatus] = mapped_column(
        enum_type(enums.WorkingContentStatus, "working_content_status"), nullable=False
    )
    materialized_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    last_checked_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime())
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class WorkingRevisionModel(Base):
    __tablename__ = "working_revisions"
    __table_args__ = (
        UniqueConstraint("id", "project_id", name="uq_working_revisions_id_project"),
        UniqueConstraint(
            "working_artifact_id",
            "role",
            name="uq_working_revisions_artifact_role",
        ),
        UniqueConstraint(
            "project_id", "storage_key", name="uq_working_revisions_storage_key"
        ),
        CheckConstraint("size >= 0", name="size_nonnegative"),
        CheckConstraint(
            "length(sha256) = 64 AND sha256 NOT GLOB '*[^0-9a-f]*'",
            name="sha256_canonical",
        ),
        CheckConstraint("length(trim(storage_key)) > 0", name="storage_key_not_blank"),
        CheckConstraint(
            "substr(storage_key, 1, 1) <> '/' "
            "AND instr(storage_key, '\\\\') = 0 "
            "AND instr('/' || storage_key || '/', '/../') = 0",
            name="storage_key_project_relative",
        ),
        ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(
            ["working_artifact_id", "project_id"],
            ["working_artifacts.id", "working_artifacts.project_id"],
            ondelete="RESTRICT",
        ),
        Index("ix_working_revisions_artifact", "working_artifact_id", "role"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), nullable=False)
    working_artifact_id: Mapped[str] = mapped_column(String(36), nullable=False)
    role: Mapped[enums.WorkingRevisionRole] = mapped_column(
        enum_type(enums.WorkingRevisionRole, "working_revision_role"), nullable=False
    )
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    file_modified_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    detected_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class RecoveryRunModel(Base):
    __tablename__ = "recovery_runs"
    __table_args__ = (
        UniqueConstraint("id", "project_id", name="uq_recovery_runs_id_project"),
        CheckConstraint("detected_count >= 0", name="detected_count_nonnegative"),
        CheckConstraint("recovered_count >= 0", name="recovered_count_nonnegative"),
        CheckConstraint("failed_count >= 0", name="failed_count_nonnegative"),
        ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        Index("ix_recovery_runs_project_created", "project_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), nullable=False)
    status: Mapped[enums.RecoveryRunStatus] = mapped_column(
        enum_type(enums.RecoveryRunStatus, "recovery_run_status"), nullable=False
    )
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    detected_count: Mapped[int] = mapped_column(Integer, nullable=False)
    recovered_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime())
    finished_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime())


class RecoveryItemModel(Base):
    __tablename__ = "recovery_items"
    __table_args__ = (
        UniqueConstraint("id", "project_id", name="uq_recovery_items_id_project"),
        ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(
            ["recovery_run_id", "project_id"],
            ["recovery_runs.id", "recovery_runs.project_id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("length(trim(storage_key)) > 0", name="storage_key_not_blank"),
        CheckConstraint(
            "substr(storage_key, 1, 1) <> '/' "
            "AND instr(storage_key, '\\\\') = 0 "
            "AND instr('/' || storage_key || '/', '/../') = 0",
            name="storage_key_project_relative",
        ),
        Index("ix_recovery_items_run_status", "recovery_run_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    recovery_run_id: Mapped[str] = mapped_column(String(36), nullable=False)
    project_id: Mapped[str] = mapped_column(String(36), nullable=False)
    kind: Mapped[enums.RecoveryItemKind] = mapped_column(
        enum_type(enums.RecoveryItemKind, "recovery_item_kind"), nullable=False
    )
    action: Mapped[enums.RecoveryAction] = mapped_column(
        enum_type(enums.RecoveryAction, "recovery_action"), nullable=False
    )
    status: Mapped[enums.RecoveryItemStatus] = mapped_column(
        enum_type(enums.RecoveryItemStatus, "recovery_item_status"), nullable=False
    )
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    operation_id: Mapped[Optional[str]] = mapped_column(String(128))
    size: Mapped[Optional[int]] = mapped_column(Integer)
    sha256: Mapped[Optional[str]] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    recovery_storage_key: Mapped[Optional[str]] = mapped_column(Text)
    error_code: Mapped[Optional[str]] = mapped_column(String(64))
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    updated_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime())


class SourceModel(Base):
    __tablename__ = "sources"
    __table_args__ = (
        UniqueConstraint("id", "project_id", name="uq_sources_id_project"),
        UniqueConstraint("snapshot_id", name="uq_sources_snapshot"),
        CheckConstraint("length(trim(display_name)) > 0", name="display_name_not_blank"),
        ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="RESTRICT"
        ),
        ForeignKeyConstraint(
            ["snapshot_id", "project_id"],
            ["original_snapshots.id", "original_snapshots.project_id"],
            ondelete="RESTRICT",
        ),
        Index("ix_sources_project_status", "project_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), nullable=False)
    snapshot_id: Mapped[str] = mapped_column(String(36), nullable=False)
    kind: Mapped[enums.SourceKind] = mapped_column(
        enum_type(enums.SourceKind, "source_kind"), nullable=False
    )
    display_name: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[enums.SourceStatus] = mapped_column(
        enum_type(enums.SourceStatus, "source_status"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class ProcessingJobModel(Base):
    __tablename__ = "processing_jobs"
    __table_args__ = (
        UniqueConstraint("id", "project_id", name="uq_processing_jobs_id_project"),
        CheckConstraint("warning_count >= 0", name="warning_count_nonnegative"),
        CheckConstraint("error_count >= 0", name="error_count_nonnegative"),
        ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="RESTRICT"
        ),
        ForeignKeyConstraint(
            ["import_session_id", "project_id"],
            ["import_sessions.id", "import_sessions.project_id"],
            ondelete="RESTRICT",
        ),
        Index(
            "uq_processing_jobs_one_active_project",
            "project_id",
            unique=True,
            sqlite_where=text("status IN ('QUEUED', 'RUNNING')"),
        ),
        Index(
            "uq_processing_jobs_import_session",
            "import_session_id",
            unique=True,
            sqlite_where=text("import_session_id IS NOT NULL"),
        ),
        Index("ix_processing_jobs_project_status", "project_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), nullable=False)
    import_session_id: Mapped[Optional[str]] = mapped_column(String(36))
    type: Mapped[enums.JobType] = mapped_column(
        enum_type(enums.JobType, "processing_job_type"), nullable=False
    )
    status: Mapped[enums.JobStatus] = mapped_column(
        enum_type(enums.JobStatus, "processing_job_status"), nullable=False
    )
    requested_by: Mapped[str] = mapped_column(String(255), nullable=False)
    policy_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime())
    finished_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime())
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class NodeModel(Base):
    __tablename__ = "nodes"
    __table_args__ = (
        UniqueConstraint("id", "project_id", name="uq_nodes_id_project"),
        UniqueConstraint("id", "project_id", "source_id", name="uq_nodes_id_project_source"),
        CheckConstraint("depth >= 0", name="depth_nonnegative"),
        CheckConstraint(
            "declared_size IS NULL OR declared_size >= 0",
            name="declared_size_nonnegative",
        ),
        CheckConstraint(
            "detection_confidence IS NULL OR "
            "(detection_confidence >= 0 AND detection_confidence <= 1)",
            name="detection_confidence_range",
        ),
        CheckConstraint("length(logical_path) > 0", name="logical_path_not_empty"),
        CheckConstraint("length(discovery_key) > 0", name="discovery_key_not_empty"),
        ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="RESTRICT"
        ),
        ForeignKeyConstraint(
            ["source_id", "project_id"],
            ["sources.id", "sources.project_id"],
            ondelete="RESTRICT",
        ),
        Index("ix_nodes_project_source", "project_id", "source_id"),
        Index("ix_nodes_project_status", "project_id", "status"),
        Index("ix_nodes_project_format", "project_id", "format"),
        Index("ix_nodes_project_logical_path", "project_id", "logical_path"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), nullable=False)
    source_id: Mapped[str] = mapped_column(String(36), nullable=False)
    kind: Mapped[enums.NodeKind] = mapped_column(
        enum_type(enums.NodeKind, "node_kind"), nullable=False
    )
    format: Mapped[enums.NodeFormat] = mapped_column(
        enum_type(enums.NodeFormat, "node_format"), nullable=False
    )
    original_name: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(String(512), nullable=False)
    logical_path: Mapped[str] = mapped_column(Text, nullable=False)
    depth: Mapped[int] = mapped_column(Integer, nullable=False)
    media_type: Mapped[Optional[str]] = mapped_column(String(255))
    declared_size: Mapped[Optional[int]] = mapped_column(Integer)
    status: Mapped[enums.NodeProcessingStatus] = mapped_column(
        enum_type(enums.NodeProcessingStatus, "node_processing_status"), nullable=False
    )
    detection_method: Mapped[Optional[str]] = mapped_column(String(100))
    detection_confidence: Mapped[Optional[float]] = mapped_column(Float)
    detection_details: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    discovery_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class SourceRootModel(Base):
    __tablename__ = "source_roots"
    __table_args__ = (
        PrimaryKeyConstraint("source_id", name="pk_source_roots"),
        UniqueConstraint("node_id", name="uq_source_roots_node"),
        ForeignKeyConstraint(
            ["source_id", "project_id"],
            ["sources.id", "sources.project_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["node_id", "project_id", "source_id"],
            ["nodes.id", "nodes.project_id", "nodes.source_id"],
            ondelete="RESTRICT",
        ),
    )

    source_id: Mapped[str] = mapped_column(String(36), nullable=False)
    project_id: Mapped[str] = mapped_column(String(36), nullable=False)
    node_id: Mapped[str] = mapped_column(String(36), nullable=False)


class ArtifactModel(Base):
    __tablename__ = "artifacts"
    __table_args__ = (
        UniqueConstraint("id", "project_id", name="uq_artifacts_id_project"),
        UniqueConstraint(
            "node_id", "role", "locator", name="uq_artifacts_node_role_locator"
        ),
        CheckConstraint("size IS NULL OR size >= 0", name="size_nonnegative"),
        CheckConstraint(
            "sha256 IS NULL OR "
            "(length(sha256) = 64 AND sha256 NOT GLOB '*[^0-9a-f]*')",
            name="sha256_length",
        ),
        CheckConstraint(
            "(role = 'ORIGINAL_REFERENCE' AND scope = 'EXTERNAL_SOURCE') OR "
            "(role IN ('EXTRACTED_ARTIFACT', 'WORKSPACE_COPY') "
            "AND scope = 'PROJECT_WORKSPACE')",
            name="role_scope_compatible",
        ),
        ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="RESTRICT"
        ),
        ForeignKeyConstraint(
            ["node_id", "project_id"],
            ["nodes.id", "nodes.project_id"],
            ondelete="RESTRICT",
        ),
        Index("ix_artifacts_project_node", "project_id", "node_id"),
        Index("ix_artifacts_sha256", "sha256"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), nullable=False)
    node_id: Mapped[str] = mapped_column(String(36), nullable=False)
    role: Mapped[enums.ArtifactRole] = mapped_column(
        enum_type(enums.ArtifactRole, "artifact_role"), nullable=False
    )
    scope: Mapped[enums.ArtifactScope] = mapped_column(
        enum_type(enums.ArtifactScope, "artifact_scope"), nullable=False
    )
    locator: Mapped[str] = mapped_column(Text, nullable=False)
    size: Mapped[Optional[int]] = mapped_column(Integer)
    sha256: Mapped[Optional[str]] = mapped_column(String(64))
    integrity_status: Mapped[enums.ArtifactIntegrityStatus] = mapped_column(
        enum_type(enums.ArtifactIntegrityStatus, "artifact_integrity_status"),
        nullable=False,
    )
    observed_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime())
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class NodeRelationshipModel(Base):
    __tablename__ = "node_relationships"
    __table_args__ = (
        UniqueConstraint("id", "project_id", name="uq_node_relationships_id_project"),
        UniqueConstraint(
            "project_id", "child_node_id", name="uq_node_relationships_structural_child"
        ),
        UniqueConstraint(
            "project_id",
            "parent_node_id",
            "type",
            "discovery_key",
            name="uq_node_relationships_discovery",
        ),
        CheckConstraint("parent_node_id <> child_node_id", name="different_nodes"),
        CheckConstraint("ordinal >= 0", name="ordinal_nonnegative"),
        ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="RESTRICT"
        ),
        ForeignKeyConstraint(
            ["parent_node_id", "project_id", "source_id"],
            ["nodes.id", "nodes.project_id", "nodes.source_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["child_node_id", "project_id", "source_id"],
            ["nodes.id", "nodes.project_id", "nodes.source_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["created_by_job_id", "project_id"],
            ["processing_jobs.id", "processing_jobs.project_id"],
            ondelete="RESTRICT",
        ),
        Index("ix_node_relationships_parent", "project_id", "parent_node_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), nullable=False)
    source_id: Mapped[str] = mapped_column(String(36), nullable=False)
    parent_node_id: Mapped[str] = mapped_column(String(36), nullable=False)
    child_node_id: Mapped[str] = mapped_column(String(36), nullable=False)
    type: Mapped[enums.RelationshipType] = mapped_column(
        enum_type(enums.RelationshipType, "node_relationship_type"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    discovery_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    created_by_job_id: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class SourceEntryLocatorModel(Base):
    __tablename__ = "source_entry_locators"
    __table_args__ = (
        PrimaryKeyConstraint("relationship_id", name="pk_source_entry_locators"),
        UniqueConstraint(
            "project_id", "child_node_id", name="uq_source_entry_locators_child"
        ),
        CheckConstraint(
            "(kind = 'SNAPSHOT_ENTRY' AND snapshot_entry_id IS NOT NULL "
            "AND member_ordinal IS NULL AND expected_name IS NULL "
            "AND member_role IS NULL) OR "
            "(kind IN ('ZIP_MEMBER', 'EML_PART', 'MSG_ATTACHMENT', "
            "'SEVEN_Z_MEMBER', 'RAR_MEMBER') AND snapshot_entry_id IS NULL "
            "AND member_ordinal IS NOT NULL AND expected_name IS NOT NULL "
            "AND member_role IS NOT NULL)",
            name="kind_matches_target",
        ),
        CheckConstraint(
            "member_ordinal IS NULL OR member_ordinal >= 0",
            name="member_ordinal_nonnegative",
        ),
        ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(
            ["relationship_id", "project_id"],
            ["node_relationships.id", "node_relationships.project_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["child_node_id", "project_id"],
            ["nodes.id", "nodes.project_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["snapshot_entry_id"],
            ["original_snapshot_entries.id"],
            ondelete="RESTRICT",
        ),
        Index("ix_source_entry_locators_child", "project_id", "child_node_id"),
    )

    relationship_id: Mapped[str] = mapped_column(String(36), nullable=False)
    project_id: Mapped[str] = mapped_column(String(36), nullable=False)
    child_node_id: Mapped[str] = mapped_column(String(36), nullable=False)
    kind: Mapped[enums.MaterializationLocatorKind] = mapped_column(
        enum_type(
            enums.MaterializationLocatorKind, "materialization_locator_kind"
        ),
        nullable=False,
    )
    snapshot_entry_id: Mapped[Optional[str]] = mapped_column(String(36))
    member_ordinal: Mapped[Optional[int]] = mapped_column(Integer)
    expected_name: Mapped[Optional[str]] = mapped_column(String(1024))
    member_role: Mapped[Optional[str]] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class LineageRecordModel(Base):
    __tablename__ = "node_lineage"
    __table_args__ = (
        PrimaryKeyConstraint(
            "project_id", "ancestor_node_id", "descendant_node_id", name="pk_node_lineage"
        ),
        CheckConstraint(
            "(distance = 0 AND ancestor_node_id = descendant_node_id) OR "
            "(distance > 0 AND ancestor_node_id <> descendant_node_id)",
            name="distance_matches_identity",
        ),
        ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="RESTRICT"
        ),
        ForeignKeyConstraint(
            ["ancestor_node_id", "project_id", "source_id"],
            ["nodes.id", "nodes.project_id", "nodes.source_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["descendant_node_id", "project_id", "source_id"],
            ["nodes.id", "nodes.project_id", "nodes.source_id"],
            ondelete="RESTRICT",
        ),
        Index("ix_node_lineage_descendant", "project_id", "descendant_node_id", "distance"),
    )

    project_id: Mapped[str] = mapped_column(String(36), nullable=False)
    source_id: Mapped[str] = mapped_column(String(36), nullable=False)
    ancestor_node_id: Mapped[str] = mapped_column(String(36), nullable=False)
    descendant_node_id: Mapped[str] = mapped_column(String(36), nullable=False)
    distance: Mapped[int] = mapped_column(Integer, nullable=False)


class NodeMetadataModel(Base):
    __tablename__ = "node_metadata"
    __table_args__ = (
        UniqueConstraint("id", "project_id", name="uq_node_metadata_id_project"),
        UniqueConstraint(
            "node_id", "namespace", "key", name="uq_node_metadata_key"
        ),
        CheckConstraint("length(trim(namespace)) > 0", name="namespace_not_blank"),
        CheckConstraint("length(trim(key)) > 0", name="key_not_blank"),
        CheckConstraint(
            "(value_type = 'TEXT' AND value_text IS NOT NULL "
            "AND value_integer IS NULL AND value_real IS NULL "
            "AND value_boolean IS NULL AND value_datetime IS NULL AND value_json IS NULL) OR "
            "(value_type = 'INTEGER' AND value_text IS NULL "
            "AND value_integer IS NOT NULL AND value_real IS NULL "
            "AND value_boolean IS NULL AND value_datetime IS NULL AND value_json IS NULL) OR "
            "(value_type = 'REAL' AND value_text IS NULL "
            "AND value_integer IS NULL AND value_real IS NOT NULL "
            "AND value_boolean IS NULL AND value_datetime IS NULL AND value_json IS NULL) OR "
            "(value_type = 'BOOLEAN' AND value_text IS NULL "
            "AND value_integer IS NULL AND value_real IS NULL "
            "AND value_boolean IS NOT NULL AND value_datetime IS NULL AND value_json IS NULL) OR "
            "(value_type = 'DATETIME' AND value_text IS NULL "
            "AND value_integer IS NULL AND value_real IS NULL "
            "AND value_boolean IS NULL AND value_datetime IS NOT NULL AND value_json IS NULL) OR "
            "(value_type = 'JSON' AND value_text IS NULL "
            "AND value_integer IS NULL AND value_real IS NULL "
            "AND value_boolean IS NULL AND value_datetime IS NULL AND value_json IS NOT NULL)",
            name="exactly_one_typed_value",
        ),
        ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="RESTRICT"
        ),
        ForeignKeyConstraint(
            ["node_id", "project_id"],
            ["nodes.id", "nodes.project_id"],
            ondelete="RESTRICT",
        ),
        Index("ix_node_metadata_node", "project_id", "node_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), nullable=False)
    node_id: Mapped[str] = mapped_column(String(36), nullable=False)
    namespace: Mapped[str] = mapped_column(String(100), nullable=False)
    key: Mapped[str] = mapped_column(String(255), nullable=False)
    value_type: Mapped[enums.MetadataValueType] = mapped_column(
        enum_type(enums.MetadataValueType, "metadata_value_type"), nullable=False
    )
    value_text: Mapped[Optional[str]] = mapped_column(Text)
    value_integer: Mapped[Optional[int]] = mapped_column(Integer)
    value_real: Mapped[Optional[float]] = mapped_column(Float)
    value_boolean: Mapped[Optional[bool]] = mapped_column(Boolean)
    value_datetime: Mapped[Optional[datetime]] = mapped_column(UTCDateTime())
    value_json: Mapped[Optional[Any]] = mapped_column(JSON(none_as_null=True))
    provenance: Mapped[str] = mapped_column(String(255), nullable=False)
    observed_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime())
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class ProcessingAttemptModel(Base):
    __tablename__ = "processing_attempts"
    __table_args__ = (
        UniqueConstraint("id", "project_id", name="uq_processing_attempts_id_project"),
        UniqueConstraint(
            "node_id", "attempt_number", name="uq_processing_attempts_node_number"
        ),
        CheckConstraint("attempt_number > 0", name="attempt_number_positive"),
        CheckConstraint(
            "(error_code IS NULL AND error_category IS NULL AND error_message IS NULL "
            "AND error_stage IS NULL AND error_retryable IS NULL) OR "
            "(error_code IS NOT NULL AND error_category IS NOT NULL "
            "AND error_stage IS NOT NULL AND error_message IS NOT NULL "
            "AND error_retryable IS NOT NULL)",
            name="error_fields_complete",
        ),
        ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="RESTRICT"
        ),
        ForeignKeyConstraint(
            ["job_id", "project_id"],
            ["processing_jobs.id", "processing_jobs.project_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["node_id", "project_id"],
            ["nodes.id", "nodes.project_id"],
            ondelete="RESTRICT",
        ),
        Index(
            "uq_processing_attempts_one_active_node",
            "project_id",
            "node_id",
            unique=True,
            sqlite_where=text("status IN ('QUEUED', 'RUNNING')"),
        ),
        Index("ix_processing_attempts_job", "project_id", "job_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), nullable=False)
    job_id: Mapped[str] = mapped_column(String(36), nullable=False)
    node_id: Mapped[str] = mapped_column(String(36), nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[enums.AttemptStatus] = mapped_column(
        enum_type(enums.AttemptStatus, "processing_attempt_status"), nullable=False
    )
    stage: Mapped[enums.ProcessingStage] = mapped_column(
        enum_type(enums.ProcessingStage, "processing_stage"), nullable=False
    )
    handler_name: Mapped[Optional[str]] = mapped_column(String(255))
    handler_version: Mapped[Optional[str]] = mapped_column(String(100))
    backend_name: Mapped[Optional[str]] = mapped_column(String(255))
    backend_version: Mapped[Optional[str]] = mapped_column(String(100))
    backend_sha256: Mapped[Optional[str]] = mapped_column(String(64))
    queued_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime())
    finished_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime())
    error_code: Mapped[Optional[enums.ErrorCode]] = mapped_column(
        enum_type(enums.ErrorCode, "processing_error_code")
    )
    error_category: Mapped[Optional[enums.ErrorCategory]] = mapped_column(
        enum_type(enums.ErrorCategory, "processing_error_category")
    )
    error_stage: Mapped[Optional[enums.ProcessingStage]] = mapped_column(
        enum_type(enums.ProcessingStage, "processing_error_stage")
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    error_retryable: Mapped[Optional[bool]] = mapped_column(Boolean)
    technical_reference: Mapped[Optional[str]] = mapped_column(String(255))


class ProcessingEventModel(Base):
    __tablename__ = "processing_events"
    __table_args__ = (
        UniqueConstraint("id", "project_id", name="uq_processing_events_id_project"),
        ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="RESTRICT"
        ),
        ForeignKeyConstraint(
            ["source_id", "project_id"],
            ["sources.id", "sources.project_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["node_id", "project_id"],
            ["nodes.id", "nodes.project_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["job_id", "project_id"],
            ["processing_jobs.id", "processing_jobs.project_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["attempt_id", "project_id"],
            ["processing_attempts.id", "processing_attempts.project_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["import_session_id", "project_id"],
            ["import_sessions.id", "import_sessions.project_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["snapshot_id", "project_id"],
            ["original_snapshots.id", "original_snapshots.project_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_item_id", "project_id"],
            ["workspace_items.id", "workspace_items.project_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["working_artifact_id", "project_id"],
            ["working_artifacts.id", "working_artifacts.project_id"],
            ondelete="RESTRICT",
        ),
        Index("ix_processing_events_project_time", "project_id", "occurred_at"),
        Index("ix_processing_events_node_time", "node_id", "occurred_at"),
        Index("ix_processing_events_job_time", "job_id", "occurred_at"),
        Index(
            "ix_processing_events_import_session_time",
            "import_session_id",
            "occurred_at",
        ),
        Index(
            "ix_processing_events_workspace_item_time",
            "workspace_item_id",
            "occurred_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    event_type: Mapped[enums.EventType] = mapped_column(
        enum_type(enums.EventType, "processing_event_type"), nullable=False
    )
    project_id: Mapped[str] = mapped_column(String(36), nullable=False)
    source_id: Mapped[Optional[str]] = mapped_column(String(36))
    node_id: Mapped[Optional[str]] = mapped_column(String(36))
    job_id: Mapped[Optional[str]] = mapped_column(String(36))
    attempt_id: Mapped[Optional[str]] = mapped_column(String(36))
    import_session_id: Mapped[Optional[str]] = mapped_column(String(36))
    snapshot_id: Mapped[Optional[str]] = mapped_column(String(36))
    workspace_item_id: Mapped[Optional[str]] = mapped_column(String(36))
    working_artifact_id: Mapped[Optional[str]] = mapped_column(String(36))
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    severity: Mapped[enums.EventSeverity] = mapped_column(
        enum_type(enums.EventSeverity, "processing_event_severity"), nullable=False
    )
    previous_status: Mapped[Optional[str]] = mapped_column(String(64))
    new_status: Mapped[Optional[str]] = mapped_column(String(64))
    error_code: Mapped[Optional[enums.ErrorCode]] = mapped_column(
        enum_type(enums.ErrorCode, "processing_event_error_code")
    )
    details: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    correlation_id: Mapped[str] = mapped_column(String(36), nullable=False)
