"""rev_16: add is_admin_notified to tickets

Revision ID: a7b8c9d0e1f2
Revises: dc5dfb23860c
Create Date: 2026-02-18 11:15:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "a7b8c9d0e1f2"
down_revision = "dc5dfb23860c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'tickets', sa.Column('is_admin_notified',
                             sa.Boolean(),
                             server_default=sa.text('false'),
                             nullable=False
                             )
    )


def downgrade() -> None:
    op.drop_column('tickets', 'is_admin_notified')
