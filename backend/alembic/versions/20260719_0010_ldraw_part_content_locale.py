"""Align LDraw part locale provenance and structured parse errors."""

from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa


revision: str = "20260719_0010"
down_revision: Union[str, None] = "20260718_0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if context.is_offline_mode():
        add_alignment_columns()
        return
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("ldraw_parts"):
        return
    columns = {column["name"] for column in inspector.get_columns("ldraw_parts")}
    if "content_locale" not in columns:
        add_content_locale_column()
    if "parse_error_code" not in columns:
        op.add_column(
            "ldraw_parts",
            sa.Column("parse_error_code", sa.String(length=160), nullable=True),
        )
    if "parse_error_params_json" not in columns:
        op.add_column(
            "ldraw_parts",
            sa.Column("parse_error_params_json", sa.JSON(), nullable=True),
        )
    bind.execute(
        sa.text(
            "UPDATE ldraw_parts SET content_locale = 'en-US' "
            "WHERE content_locale IS NULL OR TRIM(content_locale) = ''"
        )
    )
    if "parse_error" in columns:
        parts = sa.table(
            "ldraw_parts",
            sa.column("id"),
            sa.column("ldraw_part_num", sa.String(length=128)),
            sa.column("parse_error", sa.Text()),
            sa.column("parse_error_code", sa.String(length=160)),
            sa.column("parse_error_params_json", sa.JSON()),
        )
        rows = bind.execute(
            sa.select(parts.c.id, parts.c.ldraw_part_num).where(
                parts.c.parse_error.is_not(None),
                parts.c.parse_error_code.is_(None),
            )
        ).all()
        for part_id, part_number in rows:
            bind.execute(
                parts.update()
                .where(parts.c.id == part_id)
                .values(
                    parse_error_code="ldraw_part.legacy_parse_failed",
                    parse_error_params_json={"partNumber": part_number},
                )
            )


def add_content_locale_column() -> None:
    op.add_column(
        "ldraw_parts",
        sa.Column(
            "content_locale",
            sa.String(length=16),
            nullable=False,
            server_default="en-US",
        ),
    )


def add_alignment_columns() -> None:
    add_content_locale_column()
    op.add_column(
        "ldraw_parts",
        sa.Column("parse_error_code", sa.String(length=160), nullable=True),
    )
    op.add_column(
        "ldraw_parts",
        sa.Column("parse_error_params_json", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    if context.is_offline_mode():
        op.drop_column("ldraw_parts", "parse_error_params_json")
        op.drop_column("ldraw_parts", "parse_error_code")
        op.drop_column("ldraw_parts", "content_locale")
        return
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("ldraw_parts"):
        return
    columns = {column["name"] for column in inspector.get_columns("ldraw_parts")}
    for column_name in (
        "parse_error_params_json",
        "parse_error_code",
        "content_locale",
    ):
        if column_name in columns:
            op.drop_column("ldraw_parts", column_name)
