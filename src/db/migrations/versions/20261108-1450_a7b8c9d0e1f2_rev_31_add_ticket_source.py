"""rev_31: add tickets.source column (ticket_source enum)

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-11-08 14:50:00.000000

"""
from alembic import op
import sqlalchemy as sa

from db import BaseModel


# revision identifiers, used by Alembic.
revision = "a7b8c9d0e1f2"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None

TicketSourceEnum = sa.Enum(
    "website",
    "bot",
    name="ticket_source",
    metadata=BaseModel.metadata
)


def upgrade() -> None:
    TicketSourceEnum.create(op.get_bind(), checkfirst=True)
    op.add_column(
        'tickets',
        sa.Column('source', TicketSourceEnum, nullable=True)
    )


def downgrade() -> None:
    op.drop_column('tickets', 'source')
    TicketSourceEnum.drop(op.get_bind(), checkfirst=True)
