"""conversation cache tokens

Revision ID: a7c41e2d9b10
Revises: ee3c7b3e7908
Create Date: 2026-10-01 10:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a7c41e2d9b10'
down_revision: str | Sequence[str] | None = 'ee3c7b3e7908'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('conversations', sa.Column('cache_read_tokens', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('conversations', sa.Column('cache_write_tokens', sa.Integer(), nullable=False, server_default='0'))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('conversations', 'cache_write_tokens')
    op.drop_column('conversations', 'cache_read_tokens')
