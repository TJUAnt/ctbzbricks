"""Bind authenticated Component uploads to exact pending Go upload-session keys."""

from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa


revision: str = "20260823_0024"
down_revision: Union[str, None] = "20260816_0023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


POLICY_NAME = "component artifacts authenticated insert"
HELPER_NAME = "public.can_upload_component_session_file(text)"
HELPER_SIGNATURE = "public.can_upload_component_session_file(object_name text)"


def upgrade() -> None:
    if not _storage_objects_exist():
        return
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
                from component_repo.upload_session_files as upload_file
                join component_repo.upload_sessions as upload_session
                  on upload_session.id = upload_file.upload_session_id
                where upload_file.storage_provider = 'supabase'
                  and upload_file.storage_bucket = 'component-artifacts'
                  and upload_file.storage_key = object_name
                  and upload_file.status = 'pending'
                  and upload_file.artifact_id is null
                  and upload_session.owner_id = auth.uid()
                  and upload_session.status = 'pending'
                  and upload_session.expires_at > now()
            )
        $$
        """
    )
    op.execute(f"revoke all on function {HELPER_NAME} from public")
    op.execute(f"grant execute on function {HELPER_NAME} to authenticated")
    op.execute(f'drop policy if exists "{POLICY_NAME}" on storage.objects')
    op.execute(
        f'create policy "{POLICY_NAME}" '
        "on storage.objects for insert to authenticated "
        "with check ("
        "bucket_id = 'component-artifacts' "
        "and public.can_upload_component_session_file(name)"
        ")"
    )


def downgrade() -> None:
    if not _storage_objects_exist():
        return
    op.execute(f'drop policy if exists "{POLICY_NAME}" on storage.objects')
    op.execute(
        f'create policy "{POLICY_NAME}" '
        "on storage.objects for insert to authenticated "
        "with check ("
        "bucket_id = 'component-artifacts' "
        "and (storage.foldername(name))[1] = auth.uid()::text "
        "and (storage.foldername(name))[2] = 'component-repo'"
        ")"
    )
    op.execute(f"drop function if exists {HELPER_NAME}")


def _storage_objects_exist() -> bool:
    return (
        not context.is_offline_mode()
        and op.get_bind().dialect.name == "postgresql"
        and sa.inspect(op.get_bind()).has_table("objects", schema="storage")
    )
