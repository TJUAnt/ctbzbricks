"""Persist queryable candidate search fields and component logical size."""

import re
from typing import Any, Sequence, Union

from alembic import context, op
import sqlalchemy as sa


revision: str = "20260718_0009"
down_revision: Union[str, None] = "20260718_0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PROFILE_TABLE = "fitting_candidate_profiles"
COMPONENT_TABLE = "components"


def upgrade() -> None:
    if context.is_offline_mode():
        add_profile_columns()
        add_component_columns()
        create_indexes()
        return
    bind = op.get_bind()
    if sa.inspect(bind).has_table(PROFILE_TABLE):
        ensure_profile_columns(bind)
        backfill_profile_columns(bind)
        ensure_index(
            bind,
            "idx_fitting_candidate_dimensions",
            PROFILE_TABLE,
            [
                "candidate_type",
                "profile_status",
                "height_plate",
                "width_stud",
                "depth_stud",
            ],
        )
        ensure_index(
            bind,
            "idx_fitting_candidate_sticker",
            PROFILE_TABLE,
            ["candidate_type", "is_sticker"],
        )
        ensure_index(
            bind,
            "idx_fitting_candidate_normalized_type",
            PROFILE_TABLE,
            ["candidate_type", "profile_status", "normalized_type"],
        )
    if sa.inspect(bind).has_table(COMPONENT_TABLE):
        ensure_component_columns(bind)
        backfill_component_columns(bind)
        ensure_index(
            bind,
            "idx_components_logical_size",
            COMPONENT_TABLE,
            [
                "status",
                "logical_height_plate",
                "logical_width_stud",
                "logical_depth_stud",
            ],
        )


def ensure_profile_columns(bind) -> None:
    columns = {column["name"] for column in sa.inspect(bind).get_columns(PROFILE_TABLE)}
    definitions = {
        "width_stud": sa.Column("width_stud", sa.Float(), nullable=True),
        "depth_stud": sa.Column("depth_stud", sa.Float(), nullable=True),
        "height_plate": sa.Column("height_plate", sa.Float(), nullable=True),
        "is_sticker": sa.Column(
            "is_sticker",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        "normalized_type": sa.Column("normalized_type", sa.String(length=64), nullable=True),
    }
    for column_name, definition in definitions.items():
        if column_name not in columns:
            op.add_column(PROFILE_TABLE, definition)


def ensure_component_columns(bind) -> None:
    columns = {column["name"] for column in sa.inspect(bind).get_columns(COMPONENT_TABLE)}
    for column_name in (
        "logical_width_stud",
        "logical_depth_stud",
        "logical_height_plate",
    ):
        if column_name not in columns:
            op.add_column(
                COMPONENT_TABLE,
                sa.Column(column_name, sa.Float(), nullable=True),
            )


def backfill_profile_columns(bind) -> None:
    profiles = sa.table(
        PROFILE_TABLE,
        sa.column("id", sa.BigInteger()),
        sa.column("candidate_type", sa.String(length=32)),
        sa.column("logical_size_json", sa.JSON()),
        sa.column("appearance_tags_json", sa.JSON()),
        sa.column("width_stud", sa.Float()),
        sa.column("depth_stud", sa.Float()),
        sa.column("height_plate", sa.Float()),
        sa.column("is_sticker", sa.Boolean()),
        sa.column("normalized_type", sa.String(length=64)),
    )
    rows = bind.execute(
        sa.select(
            profiles.c.id,
            profiles.c.candidate_type,
            profiles.c.logical_size_json,
            profiles.c.appearance_tags_json,
        )
    ).all()
    for profile_id, candidate_type, logical_size_json, appearance_tags_json in rows:
        logical_size = (logical_size_json or {}).get("logicalSize") or {}
        appearance = appearance_tags_json or {}
        values = (
            appearance.get("category"),
            appearance.get("name"),
            appearance.get("remarks"),
            *(appearance.get("tags") or []),
        )
        bind.execute(
            profiles.update()
            .where(profiles.c.id == profile_id)
            .values(
                width_stud=logical_size.get("widthStud"),
                depth_stud=logical_size.get("depthStud"),
                height_plate=logical_size.get("heightPlate"),
                is_sticker=(candidate_type == "part" and sticker_value(values)),
                normalized_type=standard_type(values),
            )
        )


def backfill_component_columns(bind) -> None:
    required_tables = {
        "components",
        "component_versions",
        "component_scene_snapshots",
        "ldraw_parts",
        "ldraw_part_geometry",
    }
    inspector = sa.inspect(bind)
    if not all(inspector.has_table(table_name) for table_name in required_tables):
        return
    from src.component_repo.geometry_service import backfill_component_logical_sizes

    backfill_component_logical_sizes(bind)


def normalized_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = " ".join(re.findall(r"[\w]+", value.casefold())).strip()
    return normalized or None


def sticker_value(values) -> bool:
    return any(
        token.startswith(("sticker", "decal"))
        for value in values
        if isinstance(value, str)
        for token in (normalized_text(value) or "").split()
    )


def standard_type(values) -> str | None:
    normalized_values = [
        normalized
        for value in values
        if (normalized := normalized_text(value)) is not None
    ]
    for value in normalized_values:
        for token in value.split():
            for candidate_type in ("slope", "tile", "plate"):
                if token == candidate_type or token.startswith(candidate_type):
                    return candidate_type
    return None


def ensure_index(bind, name: str, table_name: str, columns: list[str]) -> None:
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes(table_name)}
    if name not in indexes:
        op.create_index(name, table_name, columns, unique=False)


def add_profile_columns() -> None:
    op.add_column(PROFILE_TABLE, sa.Column("width_stud", sa.Float(), nullable=True))
    op.add_column(PROFILE_TABLE, sa.Column("depth_stud", sa.Float(), nullable=True))
    op.add_column(PROFILE_TABLE, sa.Column("height_plate", sa.Float(), nullable=True))
    op.add_column(
        PROFILE_TABLE,
        sa.Column("is_sticker", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        PROFILE_TABLE,
        sa.Column("normalized_type", sa.String(length=64), nullable=True),
    )


def add_component_columns() -> None:
    op.add_column(COMPONENT_TABLE, sa.Column("logical_width_stud", sa.Float(), nullable=True))
    op.add_column(COMPONENT_TABLE, sa.Column("logical_depth_stud", sa.Float(), nullable=True))
    op.add_column(COMPONENT_TABLE, sa.Column("logical_height_plate", sa.Float(), nullable=True))


def create_indexes() -> None:
    op.create_index(
        "idx_fitting_candidate_dimensions",
        PROFILE_TABLE,
        ["candidate_type", "profile_status", "height_plate", "width_stud", "depth_stud"],
    )
    op.create_index(
        "idx_fitting_candidate_sticker",
        PROFILE_TABLE,
        ["candidate_type", "is_sticker"],
    )
    op.create_index(
        "idx_fitting_candidate_normalized_type",
        PROFILE_TABLE,
        ["candidate_type", "profile_status", "normalized_type"],
    )
    op.create_index(
        "idx_components_logical_size",
        COMPONENT_TABLE,
        ["status", "logical_height_plate", "logical_width_stud", "logical_depth_stud"],
    )


def downgrade() -> None:
    if context.is_offline_mode():
        drop_all()
        return
    bind = op.get_bind()
    for table_name, index_names in (
        (
            PROFILE_TABLE,
            (
                "idx_fitting_candidate_normalized_type",
                "idx_fitting_candidate_sticker",
                "idx_fitting_candidate_dimensions",
            ),
        ),
        (COMPONENT_TABLE, ("idx_components_logical_size",)),
    ):
        if not sa.inspect(bind).has_table(table_name):
            continue
        existing_indexes = {
            index["name"] for index in sa.inspect(bind).get_indexes(table_name)
        }
        for index_name in index_names:
            if index_name in existing_indexes:
                op.drop_index(index_name, table_name=table_name)
    if sa.inspect(bind).has_table(COMPONENT_TABLE):
        columns = {
            column["name"] for column in sa.inspect(bind).get_columns(COMPONENT_TABLE)
        }
        for column_name in (
            "logical_height_plate",
            "logical_depth_stud",
            "logical_width_stud",
        ):
            if column_name in columns:
                op.drop_column(COMPONENT_TABLE, column_name)
    if sa.inspect(bind).has_table(PROFILE_TABLE):
        columns = {
            column["name"] for column in sa.inspect(bind).get_columns(PROFILE_TABLE)
        }
        for column_name in (
            "normalized_type",
            "is_sticker",
            "height_plate",
            "depth_stud",
            "width_stud",
        ):
            if column_name in columns:
                op.drop_column(PROFILE_TABLE, column_name)


def drop_all() -> None:
    op.drop_index("idx_components_logical_size", table_name=COMPONENT_TABLE)
    op.drop_index("idx_fitting_candidate_normalized_type", table_name=PROFILE_TABLE)
    op.drop_index("idx_fitting_candidate_sticker", table_name=PROFILE_TABLE)
    op.drop_index("idx_fitting_candidate_dimensions", table_name=PROFILE_TABLE)
    for column_name in (
        "logical_height_plate",
        "logical_depth_stud",
        "logical_width_stud",
    ):
        op.drop_column(COMPONENT_TABLE, column_name)
    for column_name in (
        "normalized_type",
        "is_sticker",
        "height_plate",
        "depth_stud",
        "width_stud",
    ):
        op.drop_column(PROFILE_TABLE, column_name)
