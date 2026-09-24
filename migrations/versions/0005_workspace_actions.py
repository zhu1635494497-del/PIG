"""workbench mutable workspace actions

Revision ID: 0005_workspace_actions
Revises: 0004_complex_containers
Create Date: 2026-09-23
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0005_workspace_actions"
down_revision: Union[str, None] = "0004_complex_containers"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("projects", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "workspace_revision",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch_op.create_check_constraint(
            "ck_projects_workspace_revision_nonnegative",
            "workspace_revision >= 0",
        )

    with op.batch_alter_table("import_sessions", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("target_workspace_parent_id", sa.String(length=36))
        )
        batch_op.add_column(
            sa.Column("expected_workspace_revision", sa.Integer())
        )
        batch_op.create_check_constraint(
            "ck_import_sessions_expected_workspace_revision_nonnegative",
            "expected_workspace_revision IS NULL OR expected_workspace_revision >= 0",
        )
        batch_op.create_foreign_key(
            "fk_import_sessions_target_workspace_parent_id_workspace_items",
            "workspace_items",
            ["target_workspace_parent_id", "project_id"],
            ["id", "project_id"],
            ondelete="RESTRICT",
        )
        batch_op.create_index(
            "ix_import_sessions_workspace_target",
            ["project_id", "target_workspace_parent_id"],
            unique=False,
        )


def downgrade() -> None:
    connection = op.get_bind()
    changed_projects = connection.execute(
        sa.text("SELECT COUNT(*) FROM projects WHERE workspace_revision <> 0")
    ).scalar_one()
    targeted_imports = connection.execute(
        sa.text(
            "SELECT COUNT(*) FROM import_sessions "
            "WHERE target_workspace_parent_id IS NOT NULL "
            "OR expected_workspace_revision IS NOT NULL"
        )
    ).scalar_one()
    if changed_projects or targeted_imports:
        raise RuntimeError(
            "downgrade is disabled because it would discard W5 workspace facts"
        )

    with op.batch_alter_table("import_sessions", schema=None) as batch_op:
        batch_op.drop_index("ix_import_sessions_workspace_target")
        batch_op.drop_constraint(
            "fk_import_sessions_target_workspace_parent_id_workspace_items",
            type_="foreignkey",
        )
        batch_op.drop_constraint(
            "ck_import_sessions_expected_workspace_revision_nonnegative",
            type_="check",
        )
        batch_op.drop_column("expected_workspace_revision")
        batch_op.drop_column("target_workspace_parent_id")

    with op.batch_alter_table("projects", schema=None) as batch_op:
        batch_op.drop_constraint(
            "ck_projects_workspace_revision_nonnegative", type_="check"
        )
        batch_op.drop_column("workspace_revision")
