"""workbench complex container locators and backend identity

Revision ID: 0004_complex_containers
Revises: 0003_structure_workspace
Create Date: 2026-09-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0004_complex_containers"
down_revision: Union[str, None] = "0003_structure_workspace"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_LOCATOR_KINDS = (
    "SNAPSHOT_ENTRY",
    "ZIP_MEMBER",
    "EML_PART",
    "MSG_ATTACHMENT",
    "SEVEN_Z_MEMBER",
    "RAR_MEMBER",
)


def _create_w4_locator_table() -> None:
    op.create_table(
        "source_entry_locators",
        sa.Column("relationship_id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("child_node_id", sa.String(length=36), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                *_LOCATOR_KINDS,
                name="materialization_locator_kind",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("snapshot_entry_id", sa.String(length=36), nullable=True),
        sa.Column("member_ordinal", sa.Integer(), nullable=True),
        sa.Column("expected_name", sa.String(length=1024), nullable=True),
        sa.Column("member_role", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.String(length=32), nullable=False),
        sa.CheckConstraint(
            "(kind = 'SNAPSHOT_ENTRY' AND snapshot_entry_id IS NOT NULL "
            "AND member_ordinal IS NULL AND expected_name IS NULL "
            "AND member_role IS NULL) OR "
            "(kind IN ('ZIP_MEMBER', 'EML_PART', 'MSG_ATTACHMENT', "
            "'SEVEN_Z_MEMBER', 'RAR_MEMBER') AND snapshot_entry_id IS NULL "
            "AND member_ordinal IS NOT NULL AND expected_name IS NOT NULL "
            "AND member_role IS NOT NULL)",
            name=op.f("ck_source_entry_locators_kind_matches_target"),
        ),
        sa.CheckConstraint(
            "member_ordinal IS NULL OR member_ordinal >= 0",
            name=op.f("ck_source_entry_locators_member_ordinal_nonnegative"),
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
            name=op.f("fk_source_entry_locators_relationship_id_node_relationships"),
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
            "project_id", "child_node_id", name="uq_source_entry_locators_child"
        ),
    )
    op.create_index(
        "ix_source_entry_locators_child",
        "source_entry_locators",
        ["project_id", "child_node_id"],
        unique=False,
    )


def _create_w3_locator_table() -> None:
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
            name=op.f("ck_source_entry_locators_zip_member_ordinal_nonnegative"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["relationship_id", "project_id"],
            ["node_relationships.id", "node_relationships.project_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["child_node_id", "project_id"],
            ["nodes.id", "nodes.project_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_entry_id"],
            ["original_snapshot_entries.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("relationship_id"),
        sa.UniqueConstraint(
            "project_id", "child_node_id", name="uq_source_entry_locators_child"
        ),
    )
    op.create_index(
        "ix_source_entry_locators_child",
        "source_entry_locators",
        ["project_id", "child_node_id"],
        unique=False,
    )


def _create_locator_triggers() -> None:
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


def upgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_source_entry_locators_immutable_delete")
    op.execute("DROP TRIGGER IF EXISTS trg_source_entry_locators_immutable_update")
    op.rename_table("source_entry_locators", "source_entry_locators_w3")
    op.drop_index(
        "ix_source_entry_locators_child",
        table_name="source_entry_locators_w3",
    )
    _create_w4_locator_table()
    op.execute(
        """
        INSERT INTO source_entry_locators (
            relationship_id, project_id, child_node_id, kind,
            snapshot_entry_id, member_ordinal, expected_name, member_role,
            created_at
        )
        SELECT old.relationship_id, old.project_id, old.child_node_id, old.kind,
               old.snapshot_entry_id, old.zip_member_ordinal,
               CASE WHEN old.kind = 'ZIP_MEMBER' THEN nodes.original_name END,
               CASE WHEN old.kind = 'ZIP_MEMBER' THEN 'ARCHIVE_ENTRY' END,
               old.created_at
        FROM source_entry_locators_w3 AS old
        JOIN nodes ON nodes.id = old.child_node_id
        """
    )
    op.drop_table("source_entry_locators_w3")
    _create_locator_triggers()

    with op.batch_alter_table("processing_attempts", schema=None) as batch_op:
        batch_op.add_column(sa.Column("backend_name", sa.String(length=255)))
        batch_op.add_column(sa.Column("backend_version", sa.String(length=100)))
        batch_op.add_column(sa.Column("backend_sha256", sa.String(length=64)))


def downgrade() -> None:
    connection = op.get_bind()
    incompatible = connection.execute(
        sa.text(
            "SELECT COUNT(*) FROM source_entry_locators "
            "WHERE kind NOT IN ('SNAPSHOT_ENTRY', 'ZIP_MEMBER')"
        )
    ).scalar_one()
    backend_facts = connection.execute(
        sa.text(
            "SELECT COUNT(*) FROM processing_attempts WHERE "
            "backend_name IS NOT NULL OR backend_version IS NOT NULL "
            "OR backend_sha256 IS NOT NULL"
        )
    ).scalar_one()
    if incompatible or backend_facts:
        raise RuntimeError(
            "downgrade is disabled because it would discard W4 processing facts"
        )

    with op.batch_alter_table("processing_attempts", schema=None) as batch_op:
        batch_op.drop_column("backend_sha256")
        batch_op.drop_column("backend_version")
        batch_op.drop_column("backend_name")

    op.execute("DROP TRIGGER IF EXISTS trg_source_entry_locators_immutable_delete")
    op.execute("DROP TRIGGER IF EXISTS trg_source_entry_locators_immutable_update")
    op.rename_table("source_entry_locators", "source_entry_locators_w4")
    op.drop_index(
        "ix_source_entry_locators_child",
        table_name="source_entry_locators_w4",
    )
    _create_w3_locator_table()
    op.execute(
        """
        INSERT INTO source_entry_locators (
            relationship_id, project_id, child_node_id, kind,
            snapshot_entry_id, zip_member_ordinal, created_at
        )
        SELECT relationship_id, project_id, child_node_id, kind,
               snapshot_entry_id, member_ordinal, created_at
        FROM source_entry_locators_w4
        """
    )
    op.drop_table("source_entry_locators_w4")
    _create_locator_triggers()
