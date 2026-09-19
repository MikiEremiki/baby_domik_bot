"""rev_25_add_schedule_changes_and_sync_runs

Revision ID: a1b2c3d4e5f6
Revises: f8a2b3c4d5e6
Create Date: 2026-09-19 17:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f6"
down_revision = "f8a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "schedule_sync_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("initiator_id", sa.BIGINT(), nullable=True),
        sa.Column("initiator_name", sa.String(length=255), nullable=True),
        sa.Column("spreadsheet_id", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="created"),
        sa.Column("change_ids", sa.JSON(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("results", sa.JSON(), nullable=True),
        sa.Column("report_status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("telegram_message_id", sa.BIGINT(), nullable=True),
        sa.Column("telegram_chat_id", sa.BIGINT(), nullable=True),
        sa.Column("telegram_thread_id", sa.BIGINT(), nullable=True),
        sa.Column("report_error", sa.String(), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk__schedule_sync_runs")),
    )
    op.create_index(
        op.f("ix__schedule_sync_runs__spreadsheet_id"),
        "schedule_sync_runs",
        ["spreadsheet_id"],
        unique=False,
    )

    op.create_table(
        "schedule_changes",
        sa.Column("id", sa.BIGINT(), autoincrement=True, nullable=False),
        sa.Column("schedule_event_id", sa.BIGINT(), nullable=False),
        sa.Column("author_id", sa.BIGINT(), nullable=True),
        sa.Column("author_name", sa.String(length=255), nullable=True),
        sa.Column("source", sa.String(length=50), nullable=False, server_default="schedule_hl"),
        sa.Column("operation_key", sa.String(length=100), nullable=True),
        sa.Column("operation_type", sa.String(length=20), nullable=False),
        sa.Column("snapshot_before", sa.JSON(), nullable=True),
        sa.Column("snapshot_after", sa.JSON(), nullable=False),
        sa.Column("changed_fields", sa.JSON(), nullable=False),
        sa.Column("report_status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("telegram_message_id", sa.BIGINT(), nullable=True),
        sa.Column("telegram_chat_id", sa.BIGINT(), nullable=True),
        sa.Column("telegram_thread_id", sa.BIGINT(), nullable=True),
        sa.Column("report_error", sa.String(), nullable=True),
        sa.Column("sync_status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("sync_run_id", sa.String(length=36), nullable=True),
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
            ["schedule_event_id"],
            ["schedule_events.id"],
            name=op.f("fk__schedule_changes__schedule_event_id__schedule_events"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["sync_run_id"],
            ["schedule_sync_runs.id"],
            name=op.f("fk__schedule_changes__sync_run_id__schedule_sync_runs"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk__schedule_changes")),
    )
    op.create_index(
        op.f("ix__schedule_changes__schedule_event_id"),
        "schedule_changes",
        ["schedule_event_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix__schedule_changes__operation_key"),
        "schedule_changes",
        ["operation_key"],
        unique=False,
    )
    op.create_index(
        op.f("ix__schedule_changes__sync_run_id"),
        "schedule_changes",
        ["sync_run_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix__schedule_changes__sync_run_id"), table_name="schedule_changes")
    op.drop_index(op.f("ix__schedule_changes__operation_key"), table_name="schedule_changes")
    op.drop_index(op.f("ix__schedule_changes__schedule_event_id"), table_name="schedule_changes")
    op.drop_table("schedule_changes")
    op.drop_index(op.f("ix__schedule_sync_runs__spreadsheet_id"), table_name="schedule_sync_runs")
    op.drop_table("schedule_sync_runs")
