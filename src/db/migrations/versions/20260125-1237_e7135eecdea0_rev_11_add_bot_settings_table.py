"""add bot_settings table

Revision ID: e7135eecdea0
Revises: cedbea3f6c04
Create Date: 2026-01-25 12:37:58.021262

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "e7135eecdea0"
down_revision = "cedbea3f6c04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bot_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("value", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk__bot_settings")),
        sa.UniqueConstraint("key", name=op.f("uq__bot_settings__key")),
    )


def downgrade() -> None:
    op.drop_table("bot_settings")
