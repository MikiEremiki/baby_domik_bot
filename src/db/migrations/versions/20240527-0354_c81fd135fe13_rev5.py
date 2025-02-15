"""rev5

Revision ID: c81fd135fe13
Revises: 3302b537affc
Create Date: 2024-05-27 03:54:30.598124

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "c81fd135fe13"
down_revision = "3302b537affc"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.alter_column("schedule_events",
                    "theater_events_id",
                    new_column_name="theater_event_id")
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.alter_column("schedule_events",
                    "theater_event_id",
                    new_column_name="theater_events_id")
    # ### end Alembic commands ###
