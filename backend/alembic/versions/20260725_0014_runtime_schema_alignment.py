"""Align runtime tables before adopting Alembic as the schema authority."""

from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa


revision: str = "20260725_0014"
down_revision: Union[str, None] = "20260723_0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

STRUCTURED_ERROR_COLUMNS = {
    "ldraw_files": ("parse_error_code", "parse_error_params_json"),
    "ldraw_file_references": (
        "resolve_error_code",
        "resolve_error_params_json",
    ),
    "ldraw_shadow_files": ("parse_error_code", "parse_error_params_json"),
    "ldraw_shadow_meta_raw": (
        "parse_error_code",
        "parse_error_params_json",
    ),
    "ldraw_shadow_includes": (
        "expand_error_code",
        "expand_error_params_json",
    ),
}


def upgrade() -> None:
    bind = op.get_bind()
    if context.is_offline_mode():
        add_all_columns()
        return

    for table_name, column_names in STRUCTURED_ERROR_COLUMNS.items():
        if not sa.inspect(bind).has_table(table_name):
            continue
        add_missing_structured_error_columns(bind, table_name, column_names)

    if sa.inspect(bind).has_table("pixel_art_projects"):
        add_pixel_art_content_locale(bind)
    if sa.inspect(bind).has_table("model_fitting_jobs"):
        add_model_fitting_task_context(bind)

    migrate_legacy_reference_failures(bind)
    migrate_legacy_shadow_meta_failures(bind)
    migrate_legacy_model_fitting_failures(bind)


def add_missing_structured_error_columns(
    bind,
    table_name: str,
    column_names: tuple[str, str],
) -> None:
    columns = {
        column["name"] for column in sa.inspect(bind).get_columns(table_name)
    }
    code_column, params_column = column_names
    if code_column not in columns:
        op.add_column(
            table_name,
            sa.Column(code_column, sa.String(length=160), nullable=True),
        )
    if params_column not in columns:
        op.add_column(
            table_name,
            sa.Column(params_column, sa.JSON(), nullable=True),
        )


def add_pixel_art_content_locale(bind) -> None:
    columns = {
        column["name"]
        for column in sa.inspect(bind).get_columns("pixel_art_projects")
    }
    if "content_locale" in columns:
        return
    op.add_column(
        "pixel_art_projects",
        sa.Column(
            "content_locale",
            sa.String(length=16),
            nullable=False,
            server_default="zh-CN",
        ),
    )
    if bind.dialect.name != "sqlite":
        op.alter_column(
            "pixel_art_projects",
            "content_locale",
            server_default=None,
        )


def add_model_fitting_task_context(bind) -> None:
    table_name = "model_fitting_jobs"
    columns = {
        column["name"] for column in sa.inspect(bind).get_columns(table_name)
    }
    added_locale = "locale" not in columns
    if added_locale:
        op.add_column(
            table_name,
            sa.Column(
                "locale",
                sa.String(length=16),
                nullable=False,
                server_default="zh-CN",
            ),
        )
    added_timezone = "timezone" not in columns
    if added_timezone:
        op.add_column(
            table_name,
            sa.Column(
                "timezone",
                sa.String(length=64),
                nullable=False,
                server_default="Asia/Shanghai",
            ),
        )
    if "error_code" not in columns:
        op.add_column(
            table_name,
            sa.Column("error_code", sa.String(length=160), nullable=True),
        )
    if "error_params_json" not in columns:
        op.add_column(
            table_name,
            sa.Column("error_params_json", sa.JSON(), nullable=True),
        )
    if added_locale and bind.dialect.name != "sqlite":
        op.alter_column(table_name, "locale", server_default=None)
    if added_timezone and bind.dialect.name != "sqlite":
        op.alter_column(table_name, "timezone", server_default=None)


def migrate_legacy_reference_failures(bind) -> None:
    table_name = "ldraw_file_references"
    if not has_columns(
        bind,
        table_name,
        {
            "ref_name",
            "resolve_error",
            "resolve_error_code",
            "resolve_error_params_json",
        },
    ):
        return
    references = sa.table(
        table_name,
        sa.column("id", sa.BigInteger()),
        sa.column("ref_name", sa.String(length=256)),
        sa.column("resolve_error", sa.Text()),
        sa.column("resolve_error_code", sa.String(length=160)),
        sa.column("resolve_error_params_json", sa.JSON()),
    )
    rows = bind.execute(
        sa.select(references.c.id, references.c.ref_name).where(
            references.c.resolve_error.is_not(None),
            references.c.resolve_error_code.is_(None),
        )
    ).all()
    for reference_id, reference_name in rows:
        bind.execute(
            references.update()
            .where(references.c.id == reference_id)
            .values(
                resolve_error_code="ldraw.reference_not_found",
                resolve_error_params_json={
                    "reference": str(reference_name),
                },
            )
        )


def migrate_legacy_shadow_meta_failures(bind) -> None:
    table_name = "ldraw_shadow_meta_raw"
    if not has_columns(
        bind,
        table_name,
        {
            "line_no",
            "parse_error",
            "parse_error_code",
            "parse_error_params_json",
        },
    ):
        return
    meta_rows = sa.table(
        table_name,
        sa.column("id", sa.BigInteger()),
        sa.column("line_no", sa.Integer()),
        sa.column("parse_error", sa.Text()),
        sa.column("parse_error_code", sa.String(length=160)),
        sa.column("parse_error_params_json", sa.JSON()),
    )
    rows = bind.execute(
        sa.select(meta_rows.c.id, meta_rows.c.line_no).where(
            meta_rows.c.parse_error.is_not(None),
            meta_rows.c.parse_error_code.is_(None),
        )
    ).all()
    for meta_id, line_number in rows:
        bind.execute(
            meta_rows.update()
            .where(meta_rows.c.id == meta_id)
            .values(
                parse_error_code="ldraw.shadow.meta_parse_failed",
                parse_error_params_json={"line": line_number},
            )
        )


def migrate_legacy_model_fitting_failures(bind) -> None:
    table_name = "model_fitting_jobs"
    if not has_columns(
        bind,
        table_name,
        {"error_message", "error_code", "error_params_json"},
    ):
        return
    jobs = sa.table(
        table_name,
        sa.column("id", sa.String(length=64)),
        sa.column("error_message", sa.Text()),
        sa.column("error_code", sa.String(length=160)),
        sa.column("error_params_json", sa.JSON()),
    )
    bind.execute(
        jobs.update()
        .where(
            jobs.c.error_message.is_not(None),
            jobs.c.error_code.is_(None),
        )
        .values(
            error_code="model_fitting.create_failed",
            error_params_json={},
        )
    )


def has_columns(bind, table_name: str, required: set[str]) -> bool:
    inspector = sa.inspect(bind)
    if not inspector.has_table(table_name):
        return False
    columns = {
        column["name"] for column in inspector.get_columns(table_name)
    }
    return required.issubset(columns)


def add_all_columns() -> None:
    for table_name, column_names in STRUCTURED_ERROR_COLUMNS.items():
        code_column, params_column = column_names
        op.add_column(
            table_name,
            sa.Column(code_column, sa.String(length=160), nullable=True),
        )
        op.add_column(
            table_name,
            sa.Column(params_column, sa.JSON(), nullable=True),
        )
    op.add_column(
        "pixel_art_projects",
        sa.Column(
            "content_locale",
            sa.String(length=16),
            nullable=False,
            server_default="zh-CN",
        ),
    )
    op.add_column(
        "model_fitting_jobs",
        sa.Column(
            "locale",
            sa.String(length=16),
            nullable=False,
            server_default="zh-CN",
        ),
    )
    op.add_column(
        "model_fitting_jobs",
        sa.Column(
            "timezone",
            sa.String(length=64),
            nullable=False,
            server_default="Asia/Shanghai",
        ),
    )
    op.add_column(
        "model_fitting_jobs",
        sa.Column("error_code", sa.String(length=160), nullable=True),
    )
    op.add_column(
        "model_fitting_jobs",
        sa.Column("error_params_json", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    bind = op.get_bind()
    if context.is_offline_mode():
        drop_all_columns()
        return

    for table_name, column_names in reversed(
        tuple(STRUCTURED_ERROR_COLUMNS.items())
    ):
        if not sa.inspect(bind).has_table(table_name):
            continue
        columns = {
            column["name"]
            for column in sa.inspect(bind).get_columns(table_name)
        }
        for column_name in reversed(column_names):
            if column_name in columns:
                op.drop_column(table_name, column_name)

    for table_name, column_names in (
        ("model_fitting_jobs", ("error_params_json", "error_code", "timezone", "locale")),
        ("pixel_art_projects", ("content_locale",)),
    ):
        if not sa.inspect(bind).has_table(table_name):
            continue
        columns = {
            column["name"]
            for column in sa.inspect(bind).get_columns(table_name)
        }
        for column_name in column_names:
            if column_name in columns:
                op.drop_column(table_name, column_name)


def drop_all_columns() -> None:
    for column_name in (
        "error_params_json",
        "error_code",
        "timezone",
        "locale",
    ):
        op.drop_column("model_fitting_jobs", column_name)
    op.drop_column("pixel_art_projects", "content_locale")
    for table_name, column_names in reversed(
        tuple(STRUCTURED_ERROR_COLUMNS.items())
    ):
        for column_name in reversed(column_names):
            op.drop_column(table_name, column_name)
