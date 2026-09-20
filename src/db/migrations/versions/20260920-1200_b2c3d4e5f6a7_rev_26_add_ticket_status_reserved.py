"""rev_26_add_ticket_status_reserved

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-09-20 12:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # PostgreSQL requires autocommit for ALTER TYPE ... ADD VALUE
    # or executes within op.execute
    op.execute("ALTER TYPE ticket_status ADD VALUE IF NOT EXISTS 'RESERVED'")


def downgrade() -> None:
    # PostgreSQL does not support removing values from enum directly
    pass
