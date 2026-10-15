"""background task tool calls

Revision ID: e7c1a9b4d2f6
Revises: d5a8c3e1f907
Create Date: 2026-10-15 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'e7c1a9b4d2f6'
down_revision: str | Sequence[str] | None = 'd5a8c3e1f907'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'background_tasks',
        sa.Column(
            'tool_calls',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('background_tasks', 'tool_calls')
