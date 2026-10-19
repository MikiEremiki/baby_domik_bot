"""rev_30: add user_command_access table

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-10-18 15:45:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f6a7b8c9d0e1"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'user_command_access',
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('command', sa.String(length=50), nullable=False),
        sa.PrimaryKeyConstraint('user_id', 'command', name='pk__user_command_access'),
    )


def downgrade() -> None:
    op.drop_table('user_command_access')
