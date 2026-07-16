"""Create Component Repo parse snapshot and candidate tables."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260713_0002"
down_revision: Union[str, None] = "20260712_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "component_scene_snapshots",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("import_id", sa.String(length=36), nullable=False),
        sa.Column("schema", sa.String(length=64), nullable=False),
        sa.Column("parser_version", sa.String(length=64), nullable=False),
        sa.Column("root_model_id", sa.String(length=36), nullable=True),
        sa.Column("document_json", sa.JSON(), nullable=False),
        sa.Column("bom_json", sa.JSON(), nullable=False),
        sa.Column("parse_issues_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["import_id"], ["component_imports.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_component_scene_snapshots_import",
        "component_scene_snapshots",
        ["import_id"],
    )
    op.create_index(
        "idx_component_scene_snapshots_created_at",
        "component_scene_snapshots",
        ["created_at"],
    )
    op.create_table(
        "component_candidates",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("import_id", sa.String(length=36), nullable=False),
        sa.Column("scene_snapshot_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("summary_json", sa.JSON(), nullable=False),
        sa.Column("review_decisions_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["import_id"], ["component_imports.id"]),
        sa.ForeignKeyConstraint(["scene_snapshot_id"], ["component_scene_snapshots.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_component_candidates_import",
        "component_candidates",
        ["import_id"],
    )
    op.create_index(
        "idx_component_candidates_status",
        "component_candidates",
        ["status"],
    )
    op.create_index(
        "idx_component_candidates_created_at",
        "component_candidates",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_component_candidates_created_at", table_name="component_candidates")
    op.drop_index("idx_component_candidates_status", table_name="component_candidates")
    op.drop_index("idx_component_candidates_import", table_name="component_candidates")
    op.drop_table("component_candidates")
    op.drop_index("idx_component_scene_snapshots_created_at", table_name="component_scene_snapshots")
    op.drop_index("idx_component_scene_snapshots_import", table_name="component_scene_snapshots")
    op.drop_table("component_scene_snapshots")

