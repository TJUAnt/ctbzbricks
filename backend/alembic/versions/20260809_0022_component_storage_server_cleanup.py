"""Reserve Component artifact deletion for server-side cleanup."""

from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa


revision: str = "20260809_0022"
down_revision: Union[str, None] = "20260803_0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


POLICY_NAME = "component artifacts authenticated delete"


def upgrade() -> None:
    if not _storage_objects_exist():
        return
    op.execute(f'drop policy if exists "{POLICY_NAME}" on storage.objects')


def downgrade() -> None:
    if not _storage_objects_exist():
        return
    op.execute(f'drop policy if exists "{POLICY_NAME}" on storage.objects')
    op.execute(
        f'create policy "{POLICY_NAME}" '
        "on storage.objects for delete to authenticated "
        "using ("
        "bucket_id = 'component-artifacts' "
        "and (storage.foldername(name))[1] = auth.uid()::text "
        "and (storage.foldername(name))[2] = 'component-repo' "
        "and owner_id = auth.uid()::text"
        ")"
    )


def _storage_objects_exist() -> bool:
    return (
        not context.is_offline_mode()
        and op.get_bind().dialect.name == "postgresql"
        and sa.inspect(op.get_bind()).has_table("objects", schema="storage")
    )
