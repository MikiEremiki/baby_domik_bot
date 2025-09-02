"""rev9

Revision ID: c9f1e5a9f1a2
Revises: 06fcbbb514eb
Create Date: 2025-08-27 03:08:00.000000

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "c9f1e5a9f1a2"
down_revision = "06fcbbb514eb"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tickets",
        sa.Column("reminded_1d_at", sa.TIMESTAMP(timezone=True)),
    )


def downgrade() -> None:
    op.drop_column("tickets", "reminded_1d_at")
