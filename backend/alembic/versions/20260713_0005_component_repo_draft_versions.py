"""Create Component Repo draft version tables."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260713_0005"
down_revision: Union[str, None] = "20260713_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "components",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("category", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("current_version_id", sa.String(length=36), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("tags_json", sa.JSON(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_components_status", "components", ["status"])
    op.create_index("idx_components_category", "components", ["category"])

    op.create_table(
        "component_interfaces",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("component_candidate_id", sa.String(length=36), nullable=False),
        sa.Column("world_connector_id", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("exposure", sa.String(length=32), nullable=False),
        sa.Column("default_behavior", sa.String(length=64), nullable=False),
        sa.Column("source_connector_json", sa.JSON(), nullable=False),
        sa.Column("mechanical_roles_json", sa.JSON(), nullable=False),
        sa.Column("business_roles_json", sa.JSON(), nullable=False),
        sa.Column("requirements_json", sa.JSON(), nullable=False),
        sa.Column("review_status", sa.String(length=32), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(["component_candidate_id"], ["component_candidates.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "component_candidate_id",
            "world_connector_id",
            name="uq_component_interface_candidate_connector",
        ),
    )
    op.create_index(
        "idx_component_interfaces_candidate",
        "component_interfaces",
        ["component_candidate_id"],
    )
    op.create_index(
        "idx_component_interfaces_status",
        "component_interfaces",
        ["review_status"],
    )

    op.create_table(
        "component_versions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("component_id", sa.String(length=36), nullable=False),
        sa.Column("component_candidate_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("source_artifact_id", sa.String(length=36), nullable=False),
        sa.Column("exchange_artifact_id", sa.String(length=36), nullable=True),
        sa.Column("scene_snapshot_id", sa.String(length=36), nullable=False),
        sa.Column("parser_version", sa.String(length=64), nullable=False),
        sa.Column("part_library_version_id", sa.String(length=36), nullable=True),
        sa.Column("validation_report_id", sa.String(length=36), nullable=True),
        sa.Column("interface_signature", sa.String(length=64), nullable=False),
        sa.Column("structure_hash", sa.String(length=64), nullable=False),
        sa.Column("geometry_hash", sa.String(length=64), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["component_id"], ["components.id"]),
        sa.ForeignKeyConstraint(["component_candidate_id"], ["component_candidates.id"]),
        sa.ForeignKeyConstraint(["source_artifact_id"], ["component_artifacts.id"]),
        sa.ForeignKeyConstraint(["exchange_artifact_id"], ["component_artifacts.id"]),
        sa.ForeignKeyConstraint(["scene_snapshot_id"], ["component_scene_snapshots.id"]),
        sa.ForeignKeyConstraint(["part_library_version_id"], ["part_library_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "component_id",
            "version",
            "revision",
            name="uq_component_version_revision",
        ),
    )
    op.create_index(
        "idx_component_versions_component",
        "component_versions",
        ["component_id"],
    )
    op.create_index(
        "idx_component_versions_status",
        "component_versions",
        ["status"],
    )

    op.create_table(
        "component_validation_reports",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("component_candidate_id", sa.String(length=36), nullable=True),
        sa.Column("component_version_id", sa.String(length=36), nullable=True),
        sa.Column("validation_level", sa.String(length=32), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("checks_json", sa.JSON(), nullable=False),
        sa.Column("issues_json", sa.JSON(), nullable=False),
        sa.Column("validator_version", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["component_candidate_id"], ["component_candidates.id"]),
        sa.ForeignKeyConstraint(["component_version_id"], ["component_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_component_validation_reports_candidate",
        "component_validation_reports",
        ["component_candidate_id"],
    )
    op.create_index(
        "idx_component_validation_reports_version",
        "component_validation_reports",
        ["component_version_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_component_validation_reports_version", table_name="component_validation_reports")
    op.drop_index("idx_component_validation_reports_candidate", table_name="component_validation_reports")
    op.drop_table("component_validation_reports")
    op.drop_index("idx_component_versions_status", table_name="component_versions")
    op.drop_index("idx_component_versions_component", table_name="component_versions")
    op.drop_table("component_versions")
    op.drop_index("idx_component_interfaces_status", table_name="component_interfaces")
    op.drop_index("idx_component_interfaces_candidate", table_name="component_interfaces")
    op.drop_table("component_interfaces")
    op.drop_index("idx_components_category", table_name="components")
    op.drop_index("idx_components_status", table_name="components")
    op.drop_table("components")
