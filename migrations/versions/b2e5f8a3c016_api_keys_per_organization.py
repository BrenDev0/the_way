"""api keys per organization

A provider key belonged to one user, issued by an owner or admin. It now belongs to the
organization, one per provider, set by Xplorers staff.

Revision ID: b2e5f8a3c016
Revises: a1d4e7c92b30
Create Date: 2026-10-27 10:12:03.412907

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b2e5f8a3c016'
down_revision: Union[str, Sequence[str], None] = 'a1d4e7c92b30'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # One key per provider per organization: the owner's first, else the one set most
    # recently. The others are what the organization no longer uses.
    op.execute(
        """
        DELETE FROM api_keys WHERE id NOT IN (
            SELECT DISTINCT ON (k.organization_id, k.provider) k.id
            FROM api_keys k
            JOIN users u ON u.id = k.user_id
            ORDER BY k.organization_id, k.provider, (u.role = 'owner') DESC, k.updated_at DESC, k.id
        )
        """
    )
    op.drop_constraint('uq_api_key_user_provider', 'api_keys', type_='unique')
    op.drop_index(op.f('ix_api_keys_user_id'), table_name='api_keys')
    op.drop_column('api_keys', 'user_id')
    op.drop_column('api_keys', 'issued_by')
    op.add_column('api_keys', sa.Column('set_by', sa.Uuid(), nullable=True))
    op.create_foreign_key(None, 'api_keys', 'staff_members', ['set_by'], ['id'], ondelete='SET NULL')
    op.create_unique_constraint('uq_api_key_organization_provider', 'api_keys', ['organization_id', 'provider'])


def downgrade() -> None:
    """Downgrade schema."""
    # Back to a key per user: each organization's key goes to its owner (else its oldest
    # member). An organization with nobody left has no one to hold it, so its keys go.
    op.drop_constraint('uq_api_key_organization_provider', 'api_keys', type_='unique')
    op.drop_constraint('api_keys_set_by_fkey', 'api_keys', type_='foreignkey')
    op.drop_column('api_keys', 'set_by')
    op.add_column('api_keys', sa.Column('issued_by', sa.Uuid(), nullable=True))
    op.add_column('api_keys', sa.Column('user_id', sa.Uuid(), nullable=True))
    op.execute(
        """
        UPDATE api_keys SET user_id = (
            SELECT u.id FROM users u
            WHERE u.organization_id = api_keys.organization_id
            ORDER BY (u.role = 'owner') DESC, u.created_at, u.id
            LIMIT 1
        )
        """
    )
    op.execute("DELETE FROM api_keys WHERE user_id IS NULL")
    op.alter_column('api_keys', 'user_id', nullable=False)
    op.create_foreign_key('api_keys_user_id_fkey', 'api_keys', 'users', ['user_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('api_keys_issued_by_fkey', 'api_keys', 'users', ['issued_by'], ['id'], ondelete='SET NULL')
    op.create_index(op.f('ix_api_keys_user_id'), 'api_keys', ['user_id'], unique=False)
    op.create_unique_constraint('uq_api_key_user_provider', 'api_keys', ['user_id', 'provider'])
