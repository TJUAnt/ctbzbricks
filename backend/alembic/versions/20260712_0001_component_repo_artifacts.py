"""Create Component Repo artifact and import tables."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260712_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "component_artifacts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("artifact_type", sa.String(length=32), nullable=False),
        sa.Column("original_filename", sa.Text(), nullable=False),
        sa.Column("storage_provider", sa.String(length=32), nullable=False),
        sa.Column("storage_bucket", sa.String(length=128), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("storage_uri", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("mime_type", sa.String(length=128), nullable=False),
        sa.Column("immutable", sa.Boolean(), nullable=False),
        sa.Column("uploaded_by", sa.String(length=128), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "storage_provider",
            "storage_bucket",
            "storage_key",
            name="uq_component_artifact_storage_object",
        ),
    )
    op.create_index(
        "idx_component_artifacts_type",
        "component_artifacts",
        ["artifact_type"],
    )
    op.create_index(
        "idx_component_artifacts_sha256",
        "component_artifacts",
        ["sha256"],
    )
    op.create_index(
        "idx_component_artifacts_uploaded_at",
        "component_artifacts",
        ["uploaded_at"],
    )
    op.create_table(
        "component_imports",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("source_artifact_id", sa.String(length=36), nullable=False),
        sa.Column("exchange_artifact_id", sa.String(length=36), nullable=True),
        sa.Column("target_component_id", sa.String(length=36), nullable=True),
        sa.Column("base_version_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("parser_version", sa.String(length=64), nullable=True),
        sa.Column("part_library_version", sa.String(length=128), nullable=True),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["exchange_artifact_id"], ["component_artifacts.id"]),
        sa.ForeignKeyConstraint(["source_artifact_id"], ["component_artifacts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_component_imports_status",
        "component_imports",
        ["status"],
    )
    op.create_index(
        "idx_component_imports_created_at",
        "component_imports",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_component_imports_created_at", table_name="component_imports")
    op.drop_index("idx_component_imports_status", table_name="component_imports")
    op.drop_table("component_imports")
    op.drop_index("idx_component_artifacts_uploaded_at", table_name="component_artifacts")
    op.drop_index("idx_component_artifacts_sha256", table_name="component_artifacts")
    op.drop_index("idx_component_artifacts_type", table_name="component_artifacts")
    op.drop_table("component_artifacts")

