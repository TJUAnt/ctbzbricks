"""Add locale provenance to legacy model assets."""

from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa


revision: str = "20260718_0006"
down_revision: Union[str, None] = "20260713_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if context.is_offline_mode():
        add_content_locale_column()
        return
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("model_assets"):
        return
    columns = {column["name"] for column in inspector.get_columns("model_assets")}
    if "content_locale" in columns:
        return
    add_content_locale_column()


def add_content_locale_column() -> None:
    op.add_column(
        "model_assets",
        sa.Column(
            "content_locale",
            sa.String(length=16),
            nullable=False,
            server_default="zh-CN",
        ),
    )


def downgrade() -> None:
    if context.is_offline_mode():
        op.drop_column("model_assets", "content_locale")
        return
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("model_assets"):
        return
    columns = {column["name"] for column in inspector.get_columns("model_assets")}
    if "content_locale" in columns:
        op.drop_column("model_assets", "content_locale")
