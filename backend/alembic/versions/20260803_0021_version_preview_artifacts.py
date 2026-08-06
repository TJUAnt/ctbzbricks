"""Associate immutable component versions directly with generated GLB artifacts."""

from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa


revision: str = "20260803_0021"
down_revision: Union[str, None] = "20260730_0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "component_versions",
        sa.Column("preview_artifact_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "component_versions",
        sa.Column(
            "preview_status",
            sa.String(length=32),
            nullable=False,
            server_default="pending",
        ),
    )
    op.add_column(
        "component_versions",
        sa.Column("preview_generator_version", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "component_versions",
        sa.Column("preview_failure_code", sa.String(length=160), nullable=True),
    )
    op.add_column(
        "component_versions",
        sa.Column("preview_failure_params_json", sa.JSON(), nullable=True),
    )
    op.create_index(
        "idx_component_versions_preview_artifact",
        "component_versions",
        ["preview_artifact_id"],
    )
    op.create_index(
        "idx_component_versions_preview_status",
        "component_versions",
        ["preview_status"],
    )
    if op.get_bind().dialect.name == "postgresql":
        op.create_foreign_key(
            "fk_component_versions_preview_artifact",
            "component_versions",
            "component_artifacts",
            ["preview_artifact_id"],
            ["id"],
        )
        _install_preview_read_policy()


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        _remove_preview_read_policy()
        op.drop_constraint(
            "fk_component_versions_preview_artifact",
            "component_versions",
            type_="foreignkey",
        )
    op.drop_index(
        "idx_component_versions_preview_status",
        table_name="component_versions",
    )
    op.drop_index(
        "idx_component_versions_preview_artifact",
        table_name="component_versions",
    )
    op.drop_column("component_versions", "preview_failure_params_json")
    op.drop_column("component_versions", "preview_failure_code")
    op.drop_column("component_versions", "preview_generator_version")
    op.drop_column("component_versions", "preview_status")
    op.drop_column("component_versions", "preview_artifact_id")


def _install_preview_read_policy() -> None:
    if context.is_offline_mode() or not sa.inspect(op.get_bind()).has_table(
        "objects",
        schema="storage",
    ):
        return
    op.execute(
        """
        create or replace function public.can_read_component_preview_artifact(
            object_name text
        )
        returns boolean
        language sql
        stable
        security definer
        set search_path = ''
        as $$
            select exists (
                select 1
                from public.component_artifacts as artifact
                join public.component_versions as version
                  on version.preview_artifact_id = artifact.id
                join public.components as component
                  on component.id = version.component_id
                where artifact.storage_provider = 'supabase'
                  and artifact.storage_bucket = 'component-artifacts'
                  and artifact.storage_key = object_name
                  and version.deleted_at is null
                  and component.deleted_at is null
                  and (
                    component.created_by = 'auth:' || auth.uid()::text
                    or exists (
                        select 1
                        from public.component_subscriptions as subscription
                        where subscription.component_id = component.id
                          and subscription.user_id = auth.uid()::text
                    )
                  )
            )
        $$
        """
    )
    op.execute(
        "revoke all on function "
        "public.can_read_component_preview_artifact(text) from public"
    )
    op.execute(
        "grant execute on function "
        "public.can_read_component_preview_artifact(text) to authenticated"
    )
    op.execute(
        'drop policy if exists "component preview managed select" on storage.objects'
    )
    op.execute(
        'create policy "component preview managed select" '
        "on storage.objects for select to authenticated "
        "using ("
        "bucket_id = 'component-artifacts' "
        "and public.can_read_component_preview_artifact(name)"
        ")"
    )


def _remove_preview_read_policy() -> None:
    if context.is_offline_mode() or not sa.inspect(op.get_bind()).has_table(
        "objects",
        schema="storage",
    ):
        return
    op.execute(
        'drop policy if exists "component preview managed select" on storage.objects'
    )
    op.execute(
        "drop function if exists "
        "public.can_read_component_preview_artifact(text)"
    )
