"""rev_27: add auto_sendings and auto_sending_deliveries tables

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-10-07 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c3d4e5f6a7b8"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create ENUM type via raw SQL — safe against duplicates.
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'auto_sending_trigger') THEN
                CREATE TYPE auto_sending_trigger AS ENUM ('EVENT', 'PAYMENT');
            END IF;
        END $$;
    """)

    # auto_sendings
    op.create_table(
        "auto_sendings",
        sa.Column("id", sa.BigInteger(), nullable=False, autoincrement=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("trigger", sa.Enum("EVENT", "PAYMENT", name="auto_sending_trigger", create_type=False), nullable=False),
        sa.Column("offset_minutes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("window_start", sa.TIME(), nullable=True),
        sa.Column("window_end", sa.TIME(), nullable=True),
        sa.Column("precise", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("conditions", sa.JSON(), nullable=True),
        sa.Column("theater_event_id", sa.BigInteger(), nullable=True),
        sa.Column("text", sa.String(), nullable=False),
        sa.Column("send_via_bot", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("send_via_website", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["theater_event_id"],
            ["theater_events.id"],
            name=op.f("fk__auto_sendings__theater_event_id__theater_events"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk__auto_sendings")),
    )

    # auto_sending_deliveries
    op.create_table(
        "auto_sending_deliveries",
        sa.Column("id", sa.BigInteger(), nullable=False, autoincrement=True),
        sa.Column("auto_sending_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("dedup_key", sa.String(), nullable=False),
        sa.Column("schedule_event_id", sa.BigInteger(), nullable=True),
        sa.Column("sent_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["auto_sending_id"],
            ["auto_sendings.id"],
            name=op.f("fk__auto_sending_deliveries__auto_sending_id__auto_sendings"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.user_id"],
            name=op.f("fk__auto_sending_deliveries__user_id__users"),
        ),
        sa.ForeignKeyConstraint(
            ["schedule_event_id"],
            ["schedule_events.id"],
            name=op.f("fk__auto_sending_deliveries__schedule_event_id__schedule_events"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk__auto_sending_deliveries")),
        sa.UniqueConstraint(
            "auto_sending_id", "user_id", "dedup_key",
            name=op.f("uq__auto_sending_deliveries__auto_sending_id_user_id_dedup_key"),
        ),
    )

    # Seed data: default auto-sending templates with hardcoded text.
    # NOTE: These templates contain hardcoded Russian text and VK links.
    # To modify the template text, use the CRUD interface or admin panel,
    # not this migration. The migration is idempotent only on first run.
    # Seed: "Напоминание за день" (event, -1500 min)
    op.execute("""
        INSERT INTO auto_sendings (name, trigger, offset_minutes, window_start, window_end,
                                   precise, conditions, theater_event_id, text,
                                   send_via_bot, send_via_website, is_active)
        VALUES (
            'Напоминание за день',
            'EVENT'::auto_sending_trigger,
            -1500,
            NULL,
            NULL,
            false,
            NULL,
            NULL,
            '<b>Напоминаем о предстоящем мероприятии завтра!</b>

{event_name}
{date} {time}
{place}

<b>Номер вашего билета: {ticket_ids}</b>

<b>❗️ ВАЖНАЯ ИНФОРМАЦИЯ: В ЧЕКЕ ОБ ОПЛАТЕ УКАЗАН НОМЕР БИЛЕТА. ВХОД НА СПЕКТАКЛЬ ОСУЩЕСТВЛЯЕТСЯ ПО ИМЕНИ ИЛИ НОМЕРУ БИЛЕТА.</b>

__________

{refund_info}

Задать вопросы можно в сообщениях группы
https://vk.com/baby_theater_domik',
            true,
            false,
            true
        )
    """)

    # Seed: "Запрос отзыва" (event, +240 min, window 08:00-21:00)
    op.execute("""
        INSERT INTO auto_sendings (name, trigger, offset_minutes, window_start, window_end,
                                   precise, conditions, theater_event_id, text,
                                   send_via_bot, send_via_website, is_active)
        VALUES (
            'Запрос отзыва',
            'EVENT'::auto_sending_trigger,
            240,
            '08:00:00',
            '21:00:00',
            false,
            NULL,
            NULL,
            '',
            true,
            false,
            false
        )
    """)


def downgrade() -> None:
    op.drop_table("auto_sending_deliveries")
    op.drop_table("auto_sendings")
    op.execute("DROP TYPE IF EXISTS auto_sending_trigger")
