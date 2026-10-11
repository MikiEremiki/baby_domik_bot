"""rev_28: simplify tg_updates table, remove redundant columns

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-10-11 23:15:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop all redundant JSON columns that duplicated full_update content
    columns_to_drop = [
        "message",
        "edited_message",
        "channel_post",
        "edited_channel_post",
        "inline_query",
        "chosen_inline_result",
        "callback_query",
        "shipping_query",
        "pre_checkout_query",
        "poll",
        "poll_answer",
        "my_chat_member",
        "chat_member",
        "chat_join_request",
        "chat_boost",
        "removed_chat_boost",
        "message_reaction",
        "message_reaction_count",
        "business_connection",
        "business_message",
        "edited_business_message",
        "deleted_business_messages",
        "purchased_paid_media",
        # Drop extracted fields no longer in the model
        "message_id",
        "reply_to_message_id",
        "message_thread_id",
    ]

    for col in columns_to_drop:
        op.drop_column("tg_updates", col, if_exists=True)


def downgrade() -> None:
    # Restore all dropped columns
    op.add_column("tg_updates", sa.Column("message_thread_id", sa.BigInteger(), nullable=True))
    op.add_column("tg_updates", sa.Column("reply_to_message_id", sa.BigInteger(), nullable=True))
    op.add_column("tg_updates", sa.Column("message_id", sa.BigInteger(), nullable=True))
    op.add_column("tg_updates", sa.Column("purchased_paid_media", sa.JSON(), nullable=True))
    op.add_column("tg_updates", sa.Column("deleted_business_messages", sa.JSON(), nullable=True))
    op.add_column("tg_updates", sa.Column("edited_business_message", sa.JSON(), nullable=True))
    op.add_column("tg_updates", sa.Column("business_message", sa.JSON(), nullable=True))
    op.add_column("tg_updates", sa.Column("business_connection", sa.JSON(), nullable=True))
    op.add_column("tg_updates", sa.Column("message_reaction_count", sa.JSON(), nullable=True))
    op.add_column("tg_updates", sa.Column("message_reaction", sa.JSON(), nullable=True))
    op.add_column("tg_updates", sa.Column("removed_chat_boost", sa.JSON(), nullable=True))
    op.add_column("tg_updates", sa.Column("chat_boost", sa.JSON(), nullable=True))
    op.add_column("tg_updates", sa.Column("chat_join_request", sa.JSON(), nullable=True))
    op.add_column("tg_updates", sa.Column("chat_member", sa.JSON(), nullable=True))
    op.add_column("tg_updates", sa.Column("my_chat_member", sa.JSON(), nullable=True))
    op.add_column("tg_updates", sa.Column("poll_answer", sa.JSON(), nullable=True))
    op.add_column("tg_updates", sa.Column("poll", sa.JSON(), nullable=True))
    op.add_column("tg_updates", sa.Column("pre_checkout_query", sa.JSON(), nullable=True))
    op.add_column("tg_updates", sa.Column("shipping_query", sa.JSON(), nullable=True))
    op.add_column("tg_updates", sa.Column("callback_query", sa.JSON(), nullable=True))
    op.add_column("tg_updates", sa.Column("chosen_inline_result", sa.JSON(), nullable=True))
    op.add_column("tg_updates", sa.Column("inline_query", sa.JSON(), nullable=True))
    op.add_column("tg_updates", sa.Column("edited_channel_post", sa.JSON(), nullable=True))
    op.add_column("tg_updates", sa.Column("channel_post", sa.JSON(), nullable=True))
    op.add_column("tg_updates", sa.Column("edited_message", sa.JSON(), nullable=True))
    op.add_column("tg_updates", sa.Column("message", sa.JSON(), nullable=True))
