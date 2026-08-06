"""Align legacy Component Repo tables with structured i18n fields."""

from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa


revision: str = "20260718_0007"
down_revision: Union[str, None] = "20260718_0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if context.is_offline_mode():
        add_component_import_columns()
        add_component_content_columns()
        return
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("component_imports"):
        import_columns = {
            column["name"]
            for column in inspector.get_columns("component_imports")
        }
        if "failure_code" not in import_columns:
            op.add_column(
                "component_imports",
                sa.Column("failure_code", sa.String(length=160), nullable=True),
            )
        if "failure_params_json" not in import_columns:
            op.add_column(
                "component_imports",
                sa.Column("failure_params_json", sa.JSON(), nullable=True),
            )
        migrate_legacy_failures(bind, import_columns)
    if inspector.has_table("components"):
        component_columns = {
            column["name"]
            for column in sa.inspect(bind).get_columns("components")
        }
        if "content_kind" not in component_columns:
            op.add_column(
                "components",
                sa.Column(
                    "content_kind",
                    sa.String(length=16),
                    nullable=False,
                    server_default="user",
                ),
            )
        if "content_locale" not in component_columns:
            op.add_column(
                "components",
                sa.Column(
                    "content_locale",
                    sa.String(length=16),
                    nullable=False,
                    server_default="zh-CN",
                ),
            )


def add_component_import_columns() -> None:
    op.add_column(
        "component_imports",
        sa.Column("failure_code", sa.String(length=160), nullable=True),
    )
    op.add_column(
        "component_imports",
        sa.Column("failure_params_json", sa.JSON(), nullable=True),
    )


def add_component_content_columns() -> None:
    op.add_column(
        "components",
        sa.Column(
            "content_kind",
            sa.String(length=16),
            nullable=False,
            server_default="user",
        ),
    )
    op.add_column(
        "components",
        sa.Column(
            "content_locale",
            sa.String(length=16),
            nullable=False,
            server_default="zh-CN",
        ),
    )


def migrate_legacy_failures(bind, import_columns: set[str]) -> None:
    if "failure_reason" not in import_columns:
        return
    imports = sa.table(
        "component_imports",
        sa.column("id", sa.String(length=36)),
        sa.column("failure_reason", sa.Text()),
        sa.column("failure_code", sa.String(length=160)),
        sa.column("failure_params_json", sa.JSON()),
    )
    rows = bind.execute(
        sa.select(imports.c.id, imports.c.failure_reason).where(
            imports.c.failure_reason.is_not(None),
            imports.c.failure_code.is_(None),
        )
    ).all()
    for import_id, failure_reason in rows:
        bind.execute(
            imports.update()
            .where(imports.c.id == import_id)
            .values(
                failure_code="component_repo.legacy_failure",
                failure_params_json={"legacyMessage": str(failure_reason)},
            )
        )


def downgrade() -> None:
    if context.is_offline_mode():
        drop_alignment_columns()
        return
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("components"):
        columns = {column["name"] for column in inspector.get_columns("components")}
        if "content_locale" in columns:
            op.drop_column("components", "content_locale")
        if "content_kind" in columns:
            op.drop_column("components", "content_kind")
    if inspector.has_table("component_imports"):
        columns = {
            column["name"]
            for column in sa.inspect(bind).get_columns("component_imports")
        }
        if "failure_params_json" in columns:
            op.drop_column("component_imports", "failure_params_json")
        if "failure_code" in columns:
            op.drop_column("component_imports", "failure_code")


def drop_alignment_columns() -> None:
    op.drop_column("components", "content_locale")
    op.drop_column("components", "content_kind")
    op.drop_column("component_imports", "failure_params_json")
    op.drop_column("component_imports", "failure_code")
