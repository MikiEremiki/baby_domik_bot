"""rev_20: add link to theater_event

Revision ID: 3647621d3342
Revises: 981e90546609
Create Date: 2026-03-15 21:50:59.648752

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "3647621d3342"
down_revision = "981e90546609"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "theater_events", sa.Column("link", sa.String(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("theater_events", "link")
