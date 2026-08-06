"""Align LDraw geometry failures with the structured error contract."""

from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa


revision: str = "20260719_0011"
down_revision: Union[str, None] = "20260719_0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if context.is_offline_mode():
        add_error_columns()
        return
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_name = "ldraw_part_geometry"
    if not inspector.has_table(table_name):
        return
    columns = {column["name"] for column in inspector.get_columns(table_name)}
    if "geometry_error_code" not in columns:
        op.add_column(
            table_name,
            sa.Column("geometry_error_code", sa.String(length=160), nullable=True),
        )
    if "geometry_error_params_json" not in columns:
        op.add_column(
            table_name,
            sa.Column("geometry_error_params_json", sa.JSON(), nullable=True),
        )
    if "geometry_error" not in columns or not inspector.has_table("ldraw_parts"):
        return
    geometry = sa.table(
        table_name,
        sa.column("id", sa.BigInteger()),
        sa.column("ldraw_part_id", sa.BigInteger()),
        sa.column("geometry_status", sa.String(length=32)),
        sa.column("geometry_error", sa.Text()),
        sa.column("geometry_error_code", sa.String(length=160)),
        sa.column("geometry_error_params_json", sa.JSON()),
    )
    parts = sa.table(
        "ldraw_parts",
        sa.column("id", sa.BigInteger()),
        sa.column("ldraw_part_num", sa.String(length=128)),
    )
    rows = bind.execute(
        sa.select(
            geometry.c.id,
            geometry.c.geometry_status,
            parts.c.ldraw_part_num,
        )
        .select_from(geometry.join(parts, parts.c.id == geometry.c.ldraw_part_id))
        .where(
            geometry.c.geometry_error.is_not(None),
            geometry.c.geometry_error_code.is_(None),
        )
    ).all()
    for geometry_id, geometry_status, part_number in rows:
        bind.execute(
            geometry.update()
            .where(geometry.c.id == geometry_id)
            .values(
                geometry_error_code=(
                    "ldraw.geometry.build_partial"
                    if geometry_status == "partial"
                    else "ldraw.geometry.build_failed"
                ),
                geometry_error_params_json={
                    "partId": part_number,
                    "errorCount": 1,
                },
            )
        )


def add_error_columns() -> None:
    op.add_column(
        "ldraw_part_geometry",
        sa.Column("geometry_error_code", sa.String(length=160), nullable=True),
    )
    op.add_column(
        "ldraw_part_geometry",
        sa.Column("geometry_error_params_json", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    if context.is_offline_mode():
        op.drop_column("ldraw_part_geometry", "geometry_error_params_json")
        op.drop_column("ldraw_part_geometry", "geometry_error_code")
        return
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("ldraw_part_geometry"):
        return
    columns = {
        column["name"]
        for column in inspector.get_columns("ldraw_part_geometry")
    }
    for column_name in ("geometry_error_params_json", "geometry_error_code"):
        if column_name in columns:
            op.drop_column("ldraw_part_geometry", column_name)
