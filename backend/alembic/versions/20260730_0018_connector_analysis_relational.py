"""Persist Component connector analysis in normalized relational tables."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260730_0018"
down_revision: Union[str, None] = "20260726_0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "component_connector_analyses",
        sa.Column("component_candidate_id", sa.String(length=36), nullable=False),
        sa.Column("part_library_version_id", sa.String(length=36), nullable=False),
        sa.Column("recognition_method", sa.String(length=64), nullable=False),
        sa.Column("recognition_version", sa.String(length=64), nullable=False),
        sa.Column("calculated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["component_candidate_id"],
            ["component_candidates.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["part_library_version_id"],
            ["part_library_versions.id"],
        ),
        sa.PrimaryKeyConstraint("component_candidate_id"),
    )
    op.create_table(
        "component_connector_analysis_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("component_candidate_id", sa.String(length=36), nullable=False),
        sa.Column("part_connector_definition_id", sa.BigInteger(), nullable=False),
        sa.Column("world_connector_id", sa.String(length=255), nullable=False),
        sa.Column("part_instance_id", sa.String(length=255), nullable=False),
        sa.Column("part_ref", sa.String(length=128), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("position_x", sa.Float(), nullable=False),
        sa.Column("position_y", sa.Float(), nullable=False),
        sa.Column("position_z", sa.Float(), nullable=False),
        sa.Column("axis_x", sa.Float(), nullable=False),
        sa.Column("axis_y", sa.Float(), nullable=False),
        sa.Column("axis_z", sa.Float(), nullable=False),
        sa.Column("matrix_11", sa.Float(), nullable=False),
        sa.Column("matrix_12", sa.Float(), nullable=False),
        sa.Column("matrix_13", sa.Float(), nullable=False),
        sa.Column("matrix_21", sa.Float(), nullable=False),
        sa.Column("matrix_22", sa.Float(), nullable=False),
        sa.Column("matrix_23", sa.Float(), nullable=False),
        sa.Column("matrix_31", sa.Float(), nullable=False),
        sa.Column("matrix_32", sa.Float(), nullable=False),
        sa.Column("matrix_33", sa.Float(), nullable=False),
        sa.Column("access_axis_x", sa.Float(), nullable=False),
        sa.Column("access_axis_y", sa.Float(), nullable=False),
        sa.Column("access_axis_z", sa.Float(), nullable=False),
        sa.Column("external_interface_id", sa.String(length=36), nullable=True),
        sa.Column("eligibility_unoccupied", sa.Boolean(), nullable=False),
        sa.Column("eligibility_supported_type", sa.Boolean(), nullable=False),
        sa.Column("eligibility_outward_facing", sa.Boolean(), nullable=False),
        sa.Column(
            "eligibility_clearance_data_available",
            sa.Boolean(),
            nullable=False,
        ),
        sa.Column("eligibility_clearance_available", sa.Boolean(), nullable=False),
        sa.Column("outward_score", sa.Float(), nullable=False),
        sa.CheckConstraint(
            "state IN ('internal', 'external', 'blocked', 'unsupported', 'unresolved')",
            name="ck_component_connector_analysis_item_state",
        ),
        sa.ForeignKeyConstraint(
            ["component_candidate_id"],
            ["component_connector_analyses.component_candidate_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["part_connector_definition_id"],
            ["part_connector_definitions.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "component_candidate_id",
            "world_connector_id",
            name="uq_component_connector_analysis_item_world",
        ),
    )
    op.create_index(
        "idx_component_connector_analysis_items_candidate_state",
        "component_connector_analysis_items",
        ["component_candidate_id", "state"],
        unique=False,
    )
    op.create_index(
        "idx_component_connector_analysis_items_candidate_part",
        "component_connector_analysis_items",
        ["component_candidate_id", "part_instance_id"],
        unique=False,
    )
    op.create_table(
        "component_connector_analysis_path_nodes",
        sa.Column("analysis_item_id", sa.String(length=36), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("instance_id", sa.String(length=255), nullable=False),
        sa.ForeignKeyConstraint(
            ["analysis_item_id"],
            ["component_connector_analysis_items.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("analysis_item_id", "ordinal"),
    )
    op.create_index(
        "idx_component_connector_analysis_path_instance",
        "component_connector_analysis_path_nodes",
        ["instance_id"],
        unique=False,
    )
    op.create_table(
        "component_connector_analysis_blockers",
        sa.Column("analysis_item_id", sa.String(length=36), nullable=False),
        sa.Column("blocker_part_instance_id", sa.String(length=255), nullable=False),
        sa.ForeignKeyConstraint(
            ["analysis_item_id"],
            ["component_connector_analysis_items.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "analysis_item_id",
            "blocker_part_instance_id",
        ),
    )
    op.create_index(
        "idx_component_connector_analysis_blocker_part",
        "component_connector_analysis_blockers",
        ["blocker_part_instance_id"],
        unique=False,
    )
    op.create_table(
        "component_connector_analysis_relations",
        sa.Column("analysis_item_id", sa.String(length=36), nullable=False),
        sa.Column("assembly_relation_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["analysis_item_id"],
            ["component_connector_analysis_items.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["assembly_relation_id"],
            ["component_assembly_relations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("analysis_item_id", "assembly_relation_id"),
    )
    op.create_index(
        "idx_component_connector_analysis_relation_relation",
        "component_connector_analysis_relations",
        ["assembly_relation_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "idx_component_connector_analysis_relation_relation",
        table_name="component_connector_analysis_relations",
    )
    op.drop_table("component_connector_analysis_relations")
    op.drop_index(
        "idx_component_connector_analysis_blocker_part",
        table_name="component_connector_analysis_blockers",
    )
    op.drop_table("component_connector_analysis_blockers")
    op.drop_index(
        "idx_component_connector_analysis_path_instance",
        table_name="component_connector_analysis_path_nodes",
    )
    op.drop_table("component_connector_analysis_path_nodes")
    op.drop_index(
        "idx_component_connector_analysis_items_candidate_part",
        table_name="component_connector_analysis_items",
    )
    op.drop_index(
        "idx_component_connector_analysis_items_candidate_state",
        table_name="component_connector_analysis_items",
    )
    op.drop_table("component_connector_analysis_items")
    op.drop_table("component_connector_analyses")
