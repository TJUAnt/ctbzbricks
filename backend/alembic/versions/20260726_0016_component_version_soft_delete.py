"""Add logical deletion metadata for Components and ComponentVersions."""

from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa


revision: str = "20260726_0016"
down_revision: Union[str, None] = "20260725_0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not context.is_offline_mode():
        bind = op.get_bind()
        add_missing_deletion_columns(
            bind,
            "components",
            "idx_components_deleted",
        )
        add_missing_deletion_columns(
            bind,
            "component_versions",
            "idx_component_versions_deleted",
        )
        return

    add_deletion_columns("components", "idx_components_deleted")
    add_deletion_columns(
        "component_versions",
        "idx_component_versions_deleted",
    )


def add_deletion_columns(table_name: str, index_name: str) -> None:
    op.add_column(
        table_name,
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        table_name,
        sa.Column("deleted_by", sa.String(length=128), nullable=True),
    )
    op.create_index(index_name, table_name, ["deleted_at"], unique=False)


def add_missing_deletion_columns(
    bind,
    table_name: str,
    index_name: str,
) -> None:
    inspector = sa.inspect(bind)
    if not inspector.has_table(table_name):
        return
    columns = {column["name"] for column in inspector.get_columns(table_name)}
    if "deleted_at" not in columns:
        op.add_column(
            table_name,
            sa.Column("deleted_at", sa.DateTime(), nullable=True),
        )
    if "deleted_by" not in columns:
        op.add_column(
            table_name,
            sa.Column("deleted_by", sa.String(length=128), nullable=True),
        )
    indexes = {
        index["name"] for index in sa.inspect(bind).get_indexes(table_name)
    }
    if index_name not in indexes:
        op.create_index(index_name, table_name, ["deleted_at"], unique=False)


def downgrade() -> None:
    if not context.is_offline_mode():
        bind = op.get_bind()
        drop_existing_deletion_columns(
            bind,
            "component_versions",
            "idx_component_versions_deleted",
        )
        drop_existing_deletion_columns(
            bind,
            "components",
            "idx_components_deleted",
        )
        return

    drop_deletion_columns(
        "component_versions",
        "idx_component_versions_deleted",
    )
    drop_deletion_columns("components", "idx_components_deleted")


def drop_deletion_columns(table_name: str, index_name: str) -> None:
    op.drop_index(index_name, table_name=table_name)
    op.drop_column(table_name, "deleted_by")
    op.drop_column(table_name, "deleted_at")


def drop_existing_deletion_columns(
    bind,
    table_name: str,
    index_name: str,
) -> None:
    inspector = sa.inspect(bind)
    if not inspector.has_table(table_name):
        return
    indexes = {index["name"] for index in inspector.get_indexes(table_name)}
    if index_name in indexes:
        op.drop_index(index_name, table_name=table_name)
    columns = {column["name"] for column in inspector.get_columns(table_name)}
    if "deleted_by" in columns:
        op.drop_column(table_name, "deleted_by")
    if "deleted_at" in columns:
        op.drop_column(table_name, "deleted_at")
