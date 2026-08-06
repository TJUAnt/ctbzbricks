"""Align upload-session failures with the structured error contract."""

from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa


revision: str = "20260722_0012"
down_revision: Union[str, None] = "20260719_0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE_NAME = "component_upload_sessions"


def upgrade() -> None:
    if context.is_offline_mode():
        add_failure_columns()
        return
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(TABLE_NAME):
        create_upload_session_table()
        return
    columns = {column["name"] for column in inspector.get_columns(TABLE_NAME)}
    if "failure_code" not in columns:
        op.add_column(
            TABLE_NAME,
            sa.Column("failure_code", sa.String(length=160), nullable=True),
        )
    if "failure_params_json" not in columns:
        op.add_column(
            TABLE_NAME,
            sa.Column("failure_params_json", sa.JSON(), nullable=True),
        )


def create_upload_session_table() -> None:
    op.create_table(
        TABLE_NAME,
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("expected_uploads_json", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("failure_code", sa.String(length=160), nullable=True),
        sa.Column("failure_params_json", sa.JSON(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_component_upload_sessions_owner",
        TABLE_NAME,
        ["owner_id"],
    )
    op.create_index(
        "idx_component_upload_sessions_status",
        TABLE_NAME,
        ["status"],
    )
    op.create_index(
        "idx_component_upload_sessions_created_at",
        TABLE_NAME,
        ["created_at"],
    )


def add_failure_columns() -> None:
    op.add_column(
        TABLE_NAME,
        sa.Column("failure_code", sa.String(length=160), nullable=True),
    )
    op.add_column(
        TABLE_NAME,
        sa.Column("failure_params_json", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    if context.is_offline_mode():
        drop_failure_columns()
        return
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(TABLE_NAME):
        return
    columns = {column["name"] for column in inspector.get_columns(TABLE_NAME)}
    if "failure_params_json" in columns:
        op.drop_column(TABLE_NAME, "failure_params_json")
    if "failure_code" in columns:
        op.drop_column(TABLE_NAME, "failure_code")


def drop_failure_columns() -> None:
    op.drop_column(TABLE_NAME, "failure_params_json")
    op.drop_column(TABLE_NAME, "failure_code")
