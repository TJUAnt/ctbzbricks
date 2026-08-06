"""Add per-user Component grouping and subscription relations."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260725_0015"
down_revision: Union[str, None] = "20260725_0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "component_groups",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=128), nullable=False),
        sa.Column("parent_group_id", sa.String(length=36), nullable=True),
        sa.Column("group_type", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=True),
        sa.Column("normalized_name", sa.String(length=100), nullable=True),
        sa.Column("content_locale", sa.String(length=16), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "group_type IN ('root', 'custom')",
            name="ck_component_groups_type",
        ),
        sa.ForeignKeyConstraint(
            ["parent_group_id"],
            ["component_groups.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "owner_id",
            "parent_group_id",
            "normalized_name",
            name="uq_component_groups_sibling_name",
        ),
    )
    op.create_index(
        "idx_component_groups_owner_parent_sort",
        "component_groups",
        ["owner_id", "parent_group_id", "sort_order"],
        unique=False,
    )
    op.create_index(
        "uq_component_groups_root_owner",
        "component_groups",
        ["owner_id"],
        unique=True,
        postgresql_where=sa.text("group_type = 'root'"),
        sqlite_where=sa.text("group_type = 'root'"),
    )
    op.create_table(
        "component_group_memberships",
        sa.Column("group_id", sa.String(length=36), nullable=False),
        sa.Column("component_id", sa.String(length=36), nullable=False),
        sa.Column("added_by", sa.String(length=128), nullable=False),
        sa.Column("added_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["component_id"],
            ["components.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["component_groups.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("group_id", "component_id"),
    )
    op.create_index(
        "idx_component_group_memberships_component",
        "component_group_memberships",
        ["component_id"],
        unique=False,
    )
    op.create_table(
        "component_subscriptions",
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("component_id", sa.String(length=36), nullable=False),
        sa.Column("subscribed_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["component_id"],
            ["components.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "component_id"),
    )
    op.create_index(
        "idx_component_subscriptions_component",
        "component_subscriptions",
        ["component_id"],
        unique=False,
    )

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for table_name in (
            "component_groups",
            "component_group_memberships",
            "component_subscriptions",
        ):
            op.execute(f'ALTER TABLE "{table_name}" ENABLE ROW LEVEL SECURITY')
            op.execute(
                f"""
                DO $$
                BEGIN
                    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
                        EXECUTE 'REVOKE ALL ON TABLE "{table_name}" FROM anon';
                    END IF;
                    IF EXISTS (
                        SELECT 1 FROM pg_roles WHERE rolname = 'authenticated'
                    ) THEN
                        EXECUTE 'REVOKE ALL ON TABLE "{table_name}" FROM authenticated';
                    END IF;
                END
                $$;
                """
            )


def downgrade() -> None:
    op.drop_index(
        "idx_component_subscriptions_component",
        table_name="component_subscriptions",
    )
    op.drop_table("component_subscriptions")
    op.drop_index(
        "idx_component_group_memberships_component",
        table_name="component_group_memberships",
    )
    op.drop_table("component_group_memberships")
    op.drop_index(
        "uq_component_groups_root_owner",
        table_name="component_groups",
    )
    op.drop_index(
        "idx_component_groups_owner_parent_sort",
        table_name="component_groups",
    )
    op.drop_table("component_groups")
