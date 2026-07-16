"""Create frozen part connector definition table."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260713_0004"
down_revision: Union[str, None] = "20260713_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "part_connector_definitions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("part_library_version_id", sa.String(length=36), nullable=False),
        sa.Column("source_connector_id", sa.BigInteger(), nullable=False),
        sa.Column("ldraw_part_num", sa.String(length=128), nullable=False),
        sa.Column("connector_kind", sa.String(length=64), nullable=False),
        sa.Column("normalized_connector_type", sa.String(length=64), nullable=True),
        sa.Column("connector_group", sa.String(length=128), nullable=True),
        sa.Column("connector_gender", sa.String(length=16), nullable=True),
        sa.Column("pos_x", sa.Float(), nullable=False),
        sa.Column("pos_y", sa.Float(), nullable=False),
        sa.Column("pos_z", sa.Float(), nullable=False),
        sa.Column("ori_11", sa.Float(), nullable=False),
        sa.Column("ori_12", sa.Float(), nullable=False),
        sa.Column("ori_13", sa.Float(), nullable=False),
        sa.Column("ori_21", sa.Float(), nullable=False),
        sa.Column("ori_22", sa.Float(), nullable=False),
        sa.Column("ori_23", sa.Float(), nullable=False),
        sa.Column("ori_31", sa.Float(), nullable=False),
        sa.Column("ori_32", sa.Float(), nullable=False),
        sa.Column("ori_33", sa.Float(), nullable=False),
        sa.Column("direction_x", sa.Float(), nullable=True),
        sa.Column("direction_y", sa.Float(), nullable=True),
        sa.Column("direction_z", sa.Float(), nullable=True),
        sa.Column("direction_label", sa.String(length=32), nullable=True),
        sa.Column("direction_group", sa.String(length=32), nullable=True),
        sa.Column("radius", sa.Float(), nullable=True),
        sa.Column("length", sa.Float(), nullable=True),
        sa.Column("caps", sa.String(length=32), nullable=True),
        sa.Column("center_flag", sa.Boolean(), nullable=True),
        sa.Column("slide_flag", sa.Boolean(), nullable=True),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("raw_params", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["part_library_version_id"], ["part_library_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "part_library_version_id",
            "source_connector_id",
            name="uq_part_connector_definition_source",
        ),
    )
    op.create_index(
        "idx_part_connector_definitions_version",
        "part_connector_definitions",
        ["part_library_version_id"],
    )
    op.create_index(
        "idx_part_connector_definitions_part",
        "part_connector_definitions",
        ["part_library_version_id", "ldraw_part_num"],
    )
    op.create_index(
        "idx_part_connector_definitions_type",
        "part_connector_definitions",
        ["normalized_connector_type", "connector_gender"],
    )


def downgrade() -> None:
    op.drop_index("idx_part_connector_definitions_type", table_name="part_connector_definitions")
    op.drop_index("idx_part_connector_definitions_part", table_name="part_connector_definitions")
    op.drop_index("idx_part_connector_definitions_version", table_name="part_connector_definitions")
    op.drop_table("part_connector_definitions")

