"""drop deleted organizations

Revision ID: d4a7b1e8f239
Revises: c3f6a9b4d127
Create Date: 2026-10-29 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd4a7b1e8f239'
down_revision: Union[str, Sequence[str], None] = 'c3f6a9b4d127'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_index(op.f('ix_deleted_organizations_organization_id'), table_name='deleted_organizations')
    op.drop_table('deleted_organizations')


def downgrade() -> None:
    """Downgrade schema."""
    op.create_table('deleted_organizations',
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('organization_name', sa.String(length=255), nullable=False),
    sa.Column('deleted_by', sa.Uuid(), nullable=True),
    sa.Column('deleted_by_email', sa.String(), nullable=False),
    sa.Column('members', sa.Integer(), nullable=False),
    sa.Column('files', sa.Integer(), nullable=False),
    sa.Column('bytes', sa.BigInteger(), nullable=False),
    sa.Column('files_removed', sa.Integer(), nullable=False),
    sa.Column('files_left', sa.Integer(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['deleted_by'], ['staff_members.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_deleted_organizations_organization_id'), 'deleted_organizations', ['organization_id'], unique=False)
