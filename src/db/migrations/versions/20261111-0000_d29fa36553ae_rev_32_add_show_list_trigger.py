"""rev_32: add SHOW_LIST value to auto_sending_trigger enum

Revision ID: d29fa36553ae
Revises: 1a2b3c4d5e6f
Create Date: 2026-11-11 00:00:00.000000

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "d29fa36553ae"
down_revision = "1a2b3c4d5e6f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE auto_sending_trigger ADD VALUE 'SHOW_LIST'")

    # Seed: default SHOW_LIST auto-sending — publish show list 30 min before event
    op.execute("""
        INSERT INTO auto_sendings (name, trigger, offset_minutes, window_start, window_end,
                                   precise, conditions, theater_event_id, text,
                                   send_via_bot, send_via_website, is_active)
        VALUES (
            'Список на показ',
            'SHOW_LIST'::auto_sending_trigger,
            -30,
            NULL,
            NULL,
            false,
            NULL,
            NULL,
            '',
            true,
            false,
            true
        )
    """)


def downgrade() -> None:
    # Remove the default SHOW_LIST auto-sending record
    op.execute("DELETE FROM auto_sendings WHERE trigger = 'SHOW_LIST'")

    # PostgreSQL does not support removing enum values directly.
    # This is irreversible without recreating the enum type.
