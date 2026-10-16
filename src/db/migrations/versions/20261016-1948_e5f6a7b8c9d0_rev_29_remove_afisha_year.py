"""rev_29: remove year column from afishas table

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-10-16 19:48:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop the old unique constraint
    op.drop_constraint("uq_afisha_month_year", "afishas", type_="unique")

    # Drop the year column
    op.drop_column("afishas", "year")

    # Create new unique constraint on month only
    op.create_unique_constraint("uq_afisha_month", "afishas", ["month"])


def downgrade() -> None:
    # Drop the new unique constraint
    op.drop_constraint("uq_afisha_month", "afishas", type_="unique")

    # Restore the year column
    op.add_column("afishas", sa.Column("year", sa.BIGINT(), nullable=False, server_default="2026"))

    # Restore the old unique constraint
    op.create_unique_constraint("uq_afisha_month_year", "afishas", ["month", "year"])
