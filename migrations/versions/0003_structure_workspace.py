"""workbench structure discovery and lazy materialization

Revision ID: 0003_structure_workspace
Revises: 0002_snapshot_import
Create Date: 2026-09-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0003_structure_workspace"
down_revision: Union[str, None] = "0002_snapshot_import"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_workspace_placement_parent_insert")
    op.execute(
        """
        CREATE TRIGGER trg_workspace_placement_parent_insert
        BEFORE INSERT ON workspace_placements
        WHEN NEW.parent_workspace_item_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM workspace_items parent
              JOIN workspace_items child
                ON child.id = NEW.workspace_item_id
               AND child.project_id = NEW.project_id
              WHERE parent.id = NEW.parent_workspace_item_id
                AND parent.project_id = NEW.project_id
                AND parent.lifecycle_status = 'ACTIVE'
                AND (
                    parent.item_kind = 'FOLDER'
                    OR (
                        parent.item_kind = 'CONTAINER_VIEW'
                        AND parent.origin_source_node_id IS NOT NULL
                        AND child.origin_source_node_id IS NOT NULL
                        AND EXISTS (
                            SELECT 1 FROM node_relationships relation
                            WHERE relation.parent_node_id = parent.origin_source_node_id
                              AND relation.child_node_id = child.origin_source_node_id
                              AND relation.project_id = NEW.project_id
                        )
                    )
                )
          )
        BEGIN
            SELECT RAISE(ABORT, 'workspace parent must be an active structural parent');
        END
        """
    )
    with op.batch_alter_table("processing_jobs", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("import_session_id", sa.String(length=36), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_processing_jobs_import_session_id_import_sessions",
            "import_sessions",
            ["import_session_id", "project_id"],
            ["id", "project_id"],
            ondelete="RESTRICT",
        )
        batch_op.create_index(
            "uq_processing_jobs_import_session",
            ["import_session_id"],
            unique=True,
            sqlite_where=sa.text("import_session_id IS NOT NULL"),
        )

    op.create_table(
        "source_entry_locators",
        sa.Column("relationship_id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("child_node_id", sa.String(length=36), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "SNAPSHOT_ENTRY",
                "ZIP_MEMBER",
                name="materialization_locator_kind",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("snapshot_entry_id", sa.String(length=36), nullable=True),
        sa.Column("zip_member_ordinal", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.String(length=32), nullable=False),
        sa.CheckConstraint(
            "(kind = 'SNAPSHOT_ENTRY' AND snapshot_entry_id IS NOT NULL "
            "AND zip_member_ordinal IS NULL) OR "
            "(kind = 'ZIP_MEMBER' AND snapshot_entry_id IS NULL "
            "AND zip_member_ordinal IS NOT NULL)",
            name=op.f("ck_source_entry_locators_kind_matches_target"),
        ),
        sa.CheckConstraint(
            "zip_member_ordinal IS NULL OR zip_member_ordinal >= 0",
            name=op.f(
                "ck_source_entry_locators_zip_member_ordinal_nonnegative"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_source_entry_locators_project_id_projects"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["relationship_id", "project_id"],
            ["node_relationships.id", "node_relationships.project_id"],
            name=op.f(
                "fk_source_entry_locators_relationship_id_node_relationships"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["child_node_id", "project_id"],
            ["nodes.id", "nodes.project_id"],
            name=op.f("fk_source_entry_locators_child_node_id_nodes"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_entry_id"],
            ["original_snapshot_entries.id"],
            name=op.f(
                "fk_source_entry_locators_snapshot_entry_id_original_snapshot_entries"
            ),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "relationship_id", name=op.f("pk_source_entry_locators")
        ),
        sa.UniqueConstraint(
            "project_id",
            "child_node_id",
            name="uq_source_entry_locators_child",
        ),
    )
    with op.batch_alter_table("source_entry_locators", schema=None) as batch_op:
        batch_op.create_index(
            "ix_source_entry_locators_child",
            ["project_id", "child_node_id"],
            unique=False,
        )
    op.execute(
        """
        CREATE TRIGGER trg_source_entry_locators_immutable_update
        BEFORE UPDATE ON source_entry_locators
        BEGIN
            SELECT RAISE(ABORT, 'source entry locator is immutable');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_source_entry_locators_immutable_delete
        BEFORE DELETE ON source_entry_locators
        BEGIN
            SELECT RAISE(ABORT, 'source entry locator is immutable');
        END
        """
    )


def downgrade() -> None:
    connection = op.get_bind()
    locator_count = connection.execute(
        sa.text("SELECT COUNT(*) FROM source_entry_locators")
    ).scalar_one()
    linked_job_count = connection.execute(
        sa.text(
            "SELECT COUNT(*) FROM processing_jobs "
            "WHERE import_session_id IS NOT NULL"
        )
    ).scalar_one()
    if locator_count or linked_job_count:
        raise RuntimeError(
            "downgrade is disabled because it would discard W3 materialization facts"
        )
    op.execute("DROP TRIGGER IF EXISTS trg_source_entry_locators_immutable_delete")
    op.execute("DROP TRIGGER IF EXISTS trg_source_entry_locators_immutable_update")
    op.drop_table("source_entry_locators")
    with op.batch_alter_table("processing_jobs", schema=None) as batch_op:
        batch_op.drop_index("uq_processing_jobs_import_session")
        batch_op.drop_constraint(
            "fk_processing_jobs_import_session_id_import_sessions",
            type_="foreignkey",
        )
        batch_op.drop_column("import_session_id")
    op.execute("DROP TRIGGER IF EXISTS trg_workspace_placement_parent_insert")
    op.execute(
        """
        CREATE TRIGGER trg_workspace_placement_parent_insert
        BEFORE INSERT ON workspace_placements
        WHEN NEW.parent_workspace_item_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM workspace_items parent
              WHERE parent.id = NEW.parent_workspace_item_id
                AND parent.project_id = NEW.project_id
                AND parent.item_kind = 'FOLDER'
                AND parent.lifecycle_status = 'ACTIVE'
          )
        BEGIN
            SELECT RAISE(ABORT, 'workspace parent must be an active ordinary folder');
        END
        """
    )
