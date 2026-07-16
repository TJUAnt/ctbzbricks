"""Create Component Repo relation candidate tables."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260713_0003"
down_revision: Union[str, None] = "20260713_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "part_library_versions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("source_table", sa.String(length=128), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("connector_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_part_library_versions_status",
        "part_library_versions",
        ["status"],
    )
    op.create_table(
        "component_relation_candidates",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("component_candidate_id", sa.String(length=36), nullable=False),
        sa.Column("part_library_version_id", sa.String(length=36), nullable=False),
        sa.Column("endpoint_a_json", sa.JSON(), nullable=False),
        sa.Column("endpoint_b_json", sa.JSON(), nullable=False),
        sa.Column("connection_type", sa.String(length=64), nullable=False),
        sa.Column("joint_type", sa.String(length=64), nullable=False),
        sa.Column("position_residual", sa.Float(), nullable=False),
        sa.Column("rotation_residual", sa.Float(), nullable=False),
        sa.Column("verified_by_tolerance", sa.Boolean(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("detection_method", sa.String(length=64), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["component_candidate_id"], ["component_candidates.id"]),
        sa.ForeignKeyConstraint(["part_library_version_id"], ["part_library_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_component_relation_candidates_candidate",
        "component_relation_candidates",
        ["component_candidate_id"],
    )
    op.create_index(
        "idx_component_relation_candidates_status",
        "component_relation_candidates",
        ["status"],
    )
    op.create_table(
        "component_assembly_relations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("component_candidate_id", sa.String(length=36), nullable=False),
        sa.Column("relation_candidate_id", sa.String(length=36), nullable=False),
        sa.Column("endpoint_a_json", sa.JSON(), nullable=False),
        sa.Column("endpoint_b_json", sa.JSON(), nullable=False),
        sa.Column("connection_type", sa.String(length=64), nullable=False),
        sa.Column("joint_type", sa.String(length=64), nullable=False),
        sa.Column("placement_json", sa.JSON(), nullable=False),
        sa.Column("confirmed_by", sa.String(length=128), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["component_candidate_id"], ["component_candidates.id"]),
        sa.ForeignKeyConstraint(["relation_candidate_id"], ["component_relation_candidates.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "relation_candidate_id",
            name="uq_component_assembly_relation_candidate",
        ),
    )
    op.create_index(
        "idx_component_assembly_relations_candidate",
        "component_assembly_relations",
        ["component_candidate_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_component_assembly_relations_candidate", table_name="component_assembly_relations")
    op.drop_table("component_assembly_relations")
    op.drop_index("idx_component_relation_candidates_status", table_name="component_relation_candidates")
    op.drop_index("idx_component_relation_candidates_candidate", table_name="component_relation_candidates")
    op.drop_table("component_relation_candidates")
    op.drop_index("idx_part_library_versions_status", table_name="part_library_versions")
    op.drop_table("part_library_versions")

