"""rev_15: add feedback tables

Revision ID: dc5dfb23860c
Revises: b1c6e14dc666
Create Date: 2026-02-16 01:32:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "dc5dfb23860c"
down_revision = "b1c6e14dc666"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # feedback_topics
    op.create_table(
        "feedback_topics",
        sa.Column("id", sa.BigInteger(), nullable=False, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("topic_id", sa.BigInteger(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.user_id"],
            name=op.f("fk__feedback_topics__user_id__users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk__feedback_topics")),
        sa.UniqueConstraint(
            "user_id", name=op.f("uq__feedback_topics__user_id")
        ),
    )

    # feedback_messages
    op.create_table(
        "feedback_messages",
        sa.Column("id", sa.BIGINT(), nullable=False, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("user_message_id", sa.BigInteger(), nullable=False),
        sa.Column("admin_message_id", sa.BigInteger(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.user_id"],
            name=op.f("fk__feedback_messages__user_id__users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk__feedback_messages")),
    )


def downgrade() -> None:
    op.drop_table("feedback_messages")
    op.drop_table("feedback_topics")
