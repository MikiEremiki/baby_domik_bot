"""rev_21: make theater_event_id optional in sales_campaigns

Revision ID: 8a737ab30cd0
Revises: 3647621d3342
Create Date: 2026-03-15 23:43:40.516298

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "8a737ab30cd0"
down_revision = "3647621d3342"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "sales_campaigns",
        "theater_event_id",
        existing_type=sa.BIGINT(),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "sales_campaigns",
        "theater_event_id",
        existing_type=sa.BIGINT(),
        nullable=False,
    )
