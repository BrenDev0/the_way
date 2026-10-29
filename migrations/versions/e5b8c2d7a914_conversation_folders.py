"""conversation folders

A person's own folders for their chats, one level deep. Deleting a folder puts its chats back in
the main list.

Revision ID: e5b8c2d7a914
Revises: d4a7b1e8f239
Create Date: 2026-10-29 15:20:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e5b8c2d7a914'
down_revision: Union[str, Sequence[str], None] = 'd4a7b1e8f239'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('conversation_folders',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=60), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'name', name='uq_conversation_folder_name')
    )
    op.create_index(op.f('ix_conversation_folders_user_id'), 'conversation_folders', ['user_id'], unique=False)
    op.add_column('conversations', sa.Column('folder_id', sa.Uuid(), nullable=True))
    op.create_index(op.f('ix_conversations_folder_id'), 'conversations', ['folder_id'], unique=False)
    op.create_foreign_key('conversations_folder_id_fkey', 'conversations', 'conversation_folders', ['folder_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('conversations_folder_id_fkey', 'conversations', type_='foreignkey')
    op.drop_index(op.f('ix_conversations_folder_id'), table_name='conversations')
    op.drop_column('conversations', 'folder_id')
    op.drop_index(op.f('ix_conversation_folders_user_id'), table_name='conversation_folders')
    op.drop_table('conversation_folders')
