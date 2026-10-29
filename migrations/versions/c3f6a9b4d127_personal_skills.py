"""personal skills

A skill belonged to the organization. It can now also belong to one person: only they see it,
and it is theirs to create and delete. Organization-wide skills are the rows with no owner.

Revision ID: c3f6a9b4d127
Revises: b2e5f8a3c016
Create Date: 2026-10-29 14:02:17.318450

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c3f6a9b4d127'
down_revision: Union[str, Sequence[str], None] = 'b2e5f8a3c016'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('skills', sa.Column('owner_id', sa.Uuid(), nullable=True))
    op.create_index(op.f('ix_skills_owner_id'), 'skills', ['owner_id'], unique=False)
    op.create_foreign_key('skills_owner_id_fkey', 'skills', 'users', ['owner_id'], ['id'], ondelete='CASCADE')
    # a name is unique among the organization's own skills, and among one person's
    op.drop_constraint('uq_skill_organization_name', 'skills', type_='unique')
    op.create_index(
        'uq_skill_organization_name', 'skills', ['organization_id', 'name'],
        unique=True, postgresql_where=sa.text('owner_id IS NULL'),
    )
    op.create_index(
        'uq_skill_owner_name', 'skills', ['owner_id', 'name'],
        unique=True, postgresql_where=sa.text('owner_id IS NOT NULL'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Personal skills have nowhere to go in the old shape: they are removed.
    op.execute("DELETE FROM skills WHERE owner_id IS NOT NULL")
    op.drop_index('uq_skill_owner_name', table_name='skills', postgresql_where=sa.text('owner_id IS NOT NULL'))
    op.drop_index('uq_skill_organization_name', table_name='skills', postgresql_where=sa.text('owner_id IS NULL'))
    op.create_unique_constraint('uq_skill_organization_name', 'skills', ['organization_id', 'name'])
    op.drop_constraint('skills_owner_id_fkey', 'skills', type_='foreignkey')
    op.drop_index(op.f('ix_skills_owner_id'), table_name='skills')
    op.drop_column('skills', 'owner_id')
