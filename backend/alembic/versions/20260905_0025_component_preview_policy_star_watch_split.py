"""Remove deprecated Star/Watch-derived access from Component preview Storage RLS."""

from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa


revision: str = "20260905_0025"
down_revision: Union[str, None] = "20260823_0024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


POLICY_NAME = "component preview managed select"
HELPER_NAME = "public.can_read_component_preview_artifact(text)"
HELPER_SIGNATURE = "public.can_read_component_preview_artifact(object_name text)"


def upgrade() -> None:
    """将 Preview 读取资格收敛为 owner 或公开版本，不再把 Star/Watch 当成授权关系。"""
    if not _storage_objects_exist():
        return
    _install_preview_read_policy(include_deprecated_star_access=False)


def downgrade() -> None:
    """恢复迁移前由旧 subscription 演化而来的 Star 读取资格，供受控回滚使用。"""
    if not _storage_objects_exist():
        return
    _install_preview_read_policy(include_deprecated_star_access=True)


def _install_preview_read_policy(*, include_deprecated_star_access: bool) -> None:
    """重建 SECURITY DEFINER helper 与 SELECT policy，避免引用已删除的关系。"""
    deprecated_legacy_access = ""
    deprecated_go_access = ""
    if include_deprecated_star_access:
        deprecated_legacy_access = """
                    or exists (
                        select 1
                        from public.component_subscriptions as subscription
                        where subscription.component_id = component.id
                          and subscription.user_id = auth.uid()::text
                    )
        """
        # Goose v14 将旧 component_subscriptions 迁移为 component_stars；回滚策略必须使用现存关系，
        # 否则 helper 会在执行时因引用已删除表而让所有 Preview 请求失败。
        deprecated_go_access = """
                    or exists (
                        select 1
                        from component_repo.component_stars as star
                        where star.component_id = component.id
                          and star.actor_id = auth.uid()
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
                    {deprecated_legacy_access}
                  )
            )
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
                    {deprecated_go_access}
                  )
            )
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
    """仅在 PostgreSQL/Supabase 提供 storage.objects 时管理 provider-owned policy。"""
    return (
        not context.is_offline_mode()
        and op.get_bind().dialect.name == "postgresql"
        and sa.inspect(op.get_bind()).has_table("objects", schema="storage")
    )
