"""Allow Storage signed URLs for Go Component Repo preview artifacts."""

from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa


revision: str = "20260816_0023"
down_revision: Union[str, None] = "20260809_0022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


POLICY_NAME = "component preview managed select"
HELPER_NAME = "public.can_read_component_preview_artifact(text)"
HELPER_SIGNATURE = "public.can_read_component_preview_artifact(object_name text)"


def upgrade() -> None:
    if not _storage_objects_exist():
        return
    _install_preview_read_policy(include_go_schema=True)


def downgrade() -> None:
    if not _storage_objects_exist():
        return
    _install_preview_read_policy(include_go_schema=False)


def _install_preview_read_policy(*, include_go_schema: bool) -> None:
    go_visibility_sql = ""
    if include_go_schema:
        go_visibility_sql = """
            or exists (
                select 1
                from component_repo.artifacts as artifact
                join component_repo.component_versions as version
                  on version.preview_artifact_id = artifact.id
                join component_repo.components as component
                  on component.id = version.component_id
                where artifact.storage_provider = 'supabase'
                  and artifact.storage_bucket = 'component-artifacts'
                  and artifact.storage_key = object_name
                  and artifact.source_kind = 'derived'
                  and artifact.verification_status = 'verified'
                  and artifact.deleted_at is null
                  and version.deleted_at is null
                  and component.deleted_at is null
                  and (
                    component.owner_id = auth.uid()
                    or (
                        component.status = 'active'
                        and version.status <> 'draft'
                    )
                    or exists (
                        select 1
                        from component_repo.component_subscriptions as subscription
                        where subscription.component_id = component.id
                          and subscription.owner_id = auth.uid()
                    )
                  )
            )
        """
    op.execute(
        f"""
        create or replace function {HELPER_SIGNATURE}
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
            {go_visibility_sql}
        $$
        """
    )
    op.execute(f"revoke all on function {HELPER_NAME} from public")
    op.execute(f"grant execute on function {HELPER_NAME} to authenticated")
    op.execute(f'drop policy if exists "{POLICY_NAME}" on storage.objects')
    op.execute(
        f'create policy "{POLICY_NAME}" '
        "on storage.objects for select to authenticated "
        "using ("
        "bucket_id = 'component-artifacts' "
        "and public.can_read_component_preview_artifact(name)"
        ")"
    )


def _storage_objects_exist() -> bool:
    return (
        not context.is_offline_mode()
        and op.get_bind().dialect.name == "postgresql"
        and sa.inspect(op.get_bind()).has_table("objects", schema="storage")
    )
