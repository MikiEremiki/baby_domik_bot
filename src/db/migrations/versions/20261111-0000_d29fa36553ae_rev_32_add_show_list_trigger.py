"""rev_32: add SHOW_LIST value to auto_sending_trigger enum

Revision ID: d29fa36553ae
Revises: 1a2b3c4d5e6f
Create Date: 2026-11-11 00:00:00.000000

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "d29fa36553ae"
down_revision = "1a2b3c4d5e6f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE auto_sending_trigger ADD VALUE 'SHOW_LIST'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values directly.
    # This is irreversible without recreating the enum type.
    pass
