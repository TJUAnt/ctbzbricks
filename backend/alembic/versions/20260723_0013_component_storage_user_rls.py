"""Align Component Repo Storage policies with userId-first object paths."""

from typing import Union

from alembic import context, op
import sqlalchemy as sa


revision: str = "20260723_0013"
down_revision: Union[str, None] = "20260722_0012"
branch_labels: Union[str, tuple[str, ...], None] = None
depends_on: Union[str, tuple[str, ...], None] = None


def upgrade() -> None:
    if context.is_offline_mode():
        return
    bind = op.get_bind()
    if (
        bind.dialect.name != "postgresql"
        or not sa.inspect(bind).has_table("objects", schema="storage")
    ):
        return
    op.execute(
        'drop policy if exists "component artifacts authenticated insert" '
        "on storage.objects"
    )
    op.execute(
        'create policy "component artifacts authenticated insert" '
        "on storage.objects for insert to authenticated "
        "with check ("
        "bucket_id = 'component-artifacts' "
        "and (storage.foldername(name))[1] = auth.uid()::text "
        "and (storage.foldername(name))[2] = 'component-repo'"
        ")"
    )
    op.execute(
        'drop policy if exists "component artifacts authenticated select" '
        "on storage.objects"
    )
    op.execute(
        'create policy "component artifacts authenticated select" '
        "on storage.objects for select to authenticated "
        "using ("
        "bucket_id = 'component-artifacts' "
        "and (storage.foldername(name))[1] = auth.uid()::text "
        "and (storage.foldername(name))[2] = 'component-repo'"
        ")"
    )
    op.execute(
        'drop policy if exists "component artifacts legacy owner select" '
        "on storage.objects"
    )
    op.execute(
        """
        create or replace function public.can_read_legacy_component_artifact(
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
                where artifact.storage_provider = 'supabase'
                  and artifact.storage_bucket = 'component-artifacts'
                  and artifact.storage_key = object_name
                  and artifact.uploaded_by = 'auth:' || auth.uid()::text
            )
        $$
        """
    )
    op.execute(
        "revoke all on function "
        "public.can_read_legacy_component_artifact(text) from public"
    )
    op.execute(
        "grant execute on function "
        "public.can_read_legacy_component_artifact(text) to authenticated"
    )
    op.execute(
        'create policy "component artifacts legacy owner select" '
        "on storage.objects for select to authenticated "
        "using ("
        "bucket_id = 'component-artifacts' "
        "and (storage.foldername(name))[1] = 'component-repo' "
        "and public.can_read_legacy_component_artifact(name)"
        ")"
    )


def downgrade() -> None:
    if context.is_offline_mode():
        return
    bind = op.get_bind()
    if (
        bind.dialect.name != "postgresql"
        or not sa.inspect(bind).has_table("objects", schema="storage")
    ):
        return
    op.execute(
        'drop policy if exists "component artifacts legacy owner select" '
        "on storage.objects"
    )
    op.execute(
        "drop function if exists "
        "public.can_read_legacy_component_artifact(text)"
    )
    op.execute(
        'drop policy if exists "component artifacts authenticated insert" '
        "on storage.objects"
    )
    op.execute(
        'create policy "component artifacts authenticated insert" '
        "on storage.objects for insert to authenticated "
        "with check ("
        "bucket_id = 'component-artifacts' "
        "and (storage.foldername(name))[1] = 'component-repo'"
        ")"
    )
    op.execute(
        'drop policy if exists "component artifacts authenticated select" '
        "on storage.objects"
    )
    op.execute(
        'create policy "component artifacts authenticated select" '
        "on storage.objects for select to authenticated "
        "using ("
        "bucket_id = 'component-artifacts' "
        "and (storage.foldername(name))[1] = 'component-repo'"
        ")"
    )
