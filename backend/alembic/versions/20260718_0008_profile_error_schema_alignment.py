"""Align persisted profile errors with the structured error contract."""

from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa


revision: str = "20260718_0008"
down_revision: Union[str, None] = "20260718_0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if context.is_offline_mode():
        add_profile_error_columns()
        return
    bind = op.get_bind()
    align_fitting_candidate_profiles(bind)
    align_part_shape_profiles(bind)


def align_fitting_candidate_profiles(bind) -> None:
    inspector = sa.inspect(bind)
    table_name = "fitting_candidate_profiles"
    if not inspector.has_table(table_name):
        return
    columns = {column["name"] for column in inspector.get_columns(table_name)}
    if "profile_error_code" not in columns:
        op.add_column(
            table_name,
            sa.Column("profile_error_code", sa.String(length=160), nullable=True),
        )
    if "profile_error_params_json" not in columns:
        op.add_column(
            table_name,
            sa.Column("profile_error_params_json", sa.JSON(), nullable=True),
        )
    if "profile_error" not in columns:
        return
    profiles = sa.table(
        table_name,
        sa.column("id", sa.BigInteger()),
        sa.column("candidate_id", sa.String(length=128)),
        sa.column("profile_error", sa.Text()),
        sa.column("profile_error_code", sa.String(length=160)),
        sa.column("profile_error_params_json", sa.JSON()),
    )
    rows = bind.execute(
        sa.select(
            profiles.c.id,
            profiles.c.candidate_id,
            profiles.c.profile_error,
        ).where(
            profiles.c.profile_error.is_not(None),
            profiles.c.profile_error_code.is_(None),
        )
    ).all()
    for profile_id, candidate_id, profile_error in rows:
        bind.execute(
            profiles.update()
            .where(profiles.c.id == profile_id)
            .values(
                profile_error_code="fitting_candidate_profile.generation_failed",
                profile_error_params_json={
                    "candidateId": str(candidate_id),
                    "legacyMessage": str(profile_error),
                },
            )
        )


def align_part_shape_profiles(bind) -> None:
    inspector = sa.inspect(bind)
    table_name = "ldraw_part_shape_profiles"
    if not inspector.has_table(table_name):
        return
    columns = {column["name"] for column in inspector.get_columns(table_name)}
    if "profile_error_type" not in columns:
        op.add_column(
            table_name,
            sa.Column("profile_error_type", sa.String(length=64), nullable=True),
        )
    if "profile_error_code" not in columns:
        op.add_column(
            table_name,
            sa.Column("profile_error_code", sa.String(length=160), nullable=True),
        )
    if "profile_error_params_json" not in columns:
        op.add_column(
            table_name,
            sa.Column("profile_error_params_json", sa.JSON(), nullable=True),
        )
    if "profile_error" not in columns:
        return
    profiles = sa.table(
        table_name,
        sa.column("id", sa.BigInteger()),
        sa.column("ldraw_part_id", sa.BigInteger()),
        sa.column("profile_error", sa.Text()),
        sa.column("profile_error_type", sa.String(length=64)),
        sa.column("profile_error_code", sa.String(length=160)),
        sa.column("profile_error_params_json", sa.JSON()),
    )
    rows = bind.execute(
        sa.select(
            profiles.c.id,
            profiles.c.ldraw_part_id,
            profiles.c.profile_error,
        ).where(
            profiles.c.profile_error.is_not(None),
            profiles.c.profile_error_code.is_(None),
        )
    ).all()
    for profile_id, part_id, profile_error in rows:
        bind.execute(
            profiles.update()
            .where(profiles.c.id == profile_id)
            .values(
                profile_error_type="unknown",
                profile_error_code="part_shape_profile.unknown",
                profile_error_params_json={
                    "ldrawPartId": part_id,
                    "legacyMessage": str(profile_error),
                },
            )
        )


def add_profile_error_columns() -> None:
    op.add_column(
        "fitting_candidate_profiles",
        sa.Column("profile_error_code", sa.String(length=160), nullable=True),
    )
    op.add_column(
        "fitting_candidate_profiles",
        sa.Column("profile_error_params_json", sa.JSON(), nullable=True),
    )
    op.add_column(
        "ldraw_part_shape_profiles",
        sa.Column("profile_error_type", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "ldraw_part_shape_profiles",
        sa.Column("profile_error_code", sa.String(length=160), nullable=True),
    )
    op.add_column(
        "ldraw_part_shape_profiles",
        sa.Column("profile_error_params_json", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    if context.is_offline_mode():
        drop_profile_error_columns()
        return
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("ldraw_part_shape_profiles"):
        columns = {
            column["name"]
            for column in inspector.get_columns("ldraw_part_shape_profiles")
        }
        for column_name in (
            "profile_error_params_json",
            "profile_error_code",
            "profile_error_type",
        ):
            if column_name in columns:
                op.drop_column("ldraw_part_shape_profiles", column_name)
    if inspector.has_table("fitting_candidate_profiles"):
        columns = {
            column["name"]
            for column in sa.inspect(bind).get_columns("fitting_candidate_profiles")
        }
        for column_name in ("profile_error_params_json", "profile_error_code"):
            if column_name in columns:
                op.drop_column("fitting_candidate_profiles", column_name)


def drop_profile_error_columns() -> None:
    op.drop_column("ldraw_part_shape_profiles", "profile_error_params_json")
    op.drop_column("ldraw_part_shape_profiles", "profile_error_code")
    op.drop_column("ldraw_part_shape_profiles", "profile_error_type")
    op.drop_column("fitting_candidate_profiles", "profile_error_params_json")
    op.drop_column("fitting_candidate_profiles", "profile_error_code")
