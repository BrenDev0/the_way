"""conversation pause

Revision ID: c3f1a9d27e54
Revises: a7c41e2d9b10
Create Date: 2026-10-06 16:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c3f1a9d27e54'
down_revision: str | Sequence[str] | None = 'a7c41e2d9b10'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('conversations', sa.Column('pause_reason', sa.String(length=32), nullable=True))
    op.add_column('conversations', sa.Column('pause_detail', sa.Text(), nullable=True))
    op.add_column('conversations', sa.Column('paused_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('conversations', sa.Column('retry_after', sa.DateTime(timezone=True), nullable=True))
    op.add_column('conversations', sa.Column('run_claim', sa.String(length=64), nullable=True))
    # A turn left "running" by a worker that died never ran again, and its conversation
    # refused every message after. Paused, it can be carried on.
    op.execute(
        "UPDATE conversations SET status = 'paused', pause_reason = 'interrupted', paused_at = now() "
        "WHERE status = 'running' AND updated_at < now() - interval '15 minutes'"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("UPDATE conversations SET status = 'failed' WHERE status = 'paused'")
    op.drop_column('conversations', 'run_claim')
    op.drop_column('conversations', 'retry_after')
    op.drop_column('conversations', 'paused_at')
    op.drop_column('conversations', 'pause_detail')
    op.drop_column('conversations', 'pause_reason')
