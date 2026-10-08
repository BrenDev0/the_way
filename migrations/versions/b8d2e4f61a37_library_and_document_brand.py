"""organization library and document brand

Revision ID: b8d2e4f61a37
Revises: c3f1a9d27e54
Create Date: 2026-10-08 18:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b8d2e4f61a37'
down_revision: str | Sequence[str] | None = 'c3f1a9d27e54'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'projects', sa.Column('shared', sa.Boolean(), server_default=sa.false(), nullable=False)
    )
    op.create_index(
        'uq_project_library_per_organization',
        'projects',
        ['organization_id'],
        unique=True,
        postgresql_where=sa.text('shared'),
    )
    op.add_column('documents', sa.Column('brand', sa.String(length=255), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('documents', 'brand')
    op.drop_index('uq_project_library_per_organization', table_name='projects')
    op.drop_column('projects', 'shared')
