"""rev_19: add weekdays to promotions

Revision ID: 981e90546609
Revises: 8d8e8b8c8a89
Create Date: 2026-03-15 12:15:09.855936

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "981e90546609"
down_revision = "8d8e8b8c8a89"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "promotions", sa.Column("weekdays", sa.BIGINT(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("promotions", "weekdays")
