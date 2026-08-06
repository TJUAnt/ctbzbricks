"""Allow authenticated owners to discard failed Component uploads."""

from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa


revision: str = "20260726_0017"
down_revision: Union[str, None] = "20260726_0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


POLICY_NAME = "component artifacts authenticated delete"


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
        f'drop policy if exists "{POLICY_NAME}" on storage.objects'
    )
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
        f'drop policy if exists "{POLICY_NAME}" on storage.objects'
    )
