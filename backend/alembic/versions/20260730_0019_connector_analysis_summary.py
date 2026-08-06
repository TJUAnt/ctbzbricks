"""Add directly readable connector summary columns."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260730_0019"
down_revision: Union[str, None] = "20260730_0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "component_connector_analysis_items",
        sa.Column("connector_type", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "component_connector_analysis_items",
        sa.Column("connector_kind", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "component_connector_analysis_items",
        sa.Column("connector_gender", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "component_connector_analysis_items",
        sa.Column("direction_label", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "component_connector_analysis_items",
        sa.Column("direction_group", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("component_connector_analysis_items", "direction_group")
    op.drop_column("component_connector_analysis_items", "direction_label")
    op.drop_column("component_connector_analysis_items", "connector_gender")
    op.drop_column("component_connector_analysis_items", "connector_kind")
    op.drop_column("component_connector_analysis_items", "connector_type")
