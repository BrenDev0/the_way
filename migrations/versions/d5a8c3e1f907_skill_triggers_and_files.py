"""skill triggers and reference files

Revision ID: d5a8c3e1f907
Revises: b8d2e4f61a37
Create Date: 2026-10-13 18:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'd5a8c3e1f907'
down_revision: str | Sequence[str] | None = 'b8d2e4f61a37'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'skills',
        sa.Column(
            'triggers',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        'skills',
        sa.Column(
            'files',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('skills', 'files')
    op.drop_column('skills', 'triggers')
