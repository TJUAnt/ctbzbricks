"""Keep only externally exposed connectors in persisted analyses."""

from typing import Sequence, Union

from alembic import op


revision: str = "20260730_0020"
down_revision: Union[str, None] = "20260730_0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "DELETE FROM component_connector_analysis_items "
        "WHERE state <> 'external'"
    )


def downgrade() -> None:
    # Removed classifications must be regenerated from their immutable snapshots.
    pass
