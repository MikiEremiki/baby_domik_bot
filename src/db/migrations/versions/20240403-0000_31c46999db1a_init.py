"""init

Revision ID: 31c46999db1a
Revises: 
Create Date: 2024-02-24 18:51:15.996266

"""
from alembic import op
import sqlalchemy as sa

from db import BaseModel

# revision identifiers, used by Alembic.
revision = "31c46999db1a"
down_revision = None
branch_labels = None
depends_on = None


TicketStatusEnum = sa.Enum(
    "CREATED",
    "PAID",
    "APPROVED",
    "REJECTED",
    "REFUNDED",
    "TRANSFERRED",
    "POSTPONED",
    "CANCELED",
    name="ticket_status",
    metadata=BaseModel.metadata
)
PriceTypeEnum = sa.Enum(
    "NONE",
    "BASE_PRICE",
    "OPTIONS",
    "INDIVIDUAL",
    name="price_type",
    metadata=BaseModel.metadata
)
TicketPriceTypeEnum = sa.Enum(
    "NONE",
    "weekday",
    "weekend",
    name="ticket_price_type",
    metadata=BaseModel.metadata
)
AgeTypeEnum = sa.Enum(
    "adult",
    "child",
    name="age_type",
    metadata=BaseModel.metadata
)


def upgrade() -> None:
    TicketStatusEnum.create(op.get_bind(), checkfirst=True)
    TicketPriceTypeEnum.create(op.get_bind(), checkfirst=True)
    PriceTypeEnum.create(op.get_bind(), checkfirst=True)
    AgeTypeEnum.create(op.get_bind(), checkfirst=True)
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        "users",
        sa.Column(
            "user_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column(
            "chat_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String()),
        sa.Column("email", sa.String()),
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
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk__users")),
    )
    op.create_table(
        "people",
        sa.Column("id", sa.BIGINT(), nullable=False),
        sa.Column("name", sa.String()),
        sa.Column("age_type", AgeTypeEnum, nullable=False),
        sa.Column("user_id", sa.BigInteger()),
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
            name=op.f("fk__people__user_id__users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk__people")),
    )
    op.create_table(
        "adults",
        sa.Column("id", sa.BIGINT(), nullable=False),
        sa.Column("phone", sa.String()),
        sa.Column("person_id", sa.BIGINT(), nullable=False),
        sa.ForeignKeyConstraint(
            ["person_id"],
            ["people.id"],
            name=op.f("fk__adults__person_id__people"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk__adults")),
    )
    op.create_table(
        "theater_events",
        sa.Column("id", sa.BIGINT(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("flag_premier", sa.Boolean(), nullable=False),
        sa.Column("min_age_child", sa.BIGINT(), nullable=False),
        sa.Column("max_age_child", sa.BIGINT()),
        sa.Column("show_emoji", sa.String()),
        sa.Column("flag_active_repertoire", sa.Boolean(), nullable=False),
        sa.Column("flag_active_bd", sa.Boolean(), nullable=False),
        sa.Column("max_num_child_bd", sa.BIGINT(), nullable=False),
        sa.Column("max_num_adult_bd", sa.BIGINT(), nullable=False),
        sa.Column("flag_indiv_cost", sa.Boolean(), nullable=False),
        sa.Column("price_type", PriceTypeEnum, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk__theater_events")),
    )
    op.create_table(
        "type_events",
        sa.Column("id", sa.BIGINT(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("name_alias", sa.String(), nullable=False),
        sa.Column("base_price_gift", sa.BIGINT()),
        sa.Column("notes", sa.String()),
        sa.PrimaryKeyConstraint("id", name=op.f("pk__type_events")),
    )
    op.create_table(
        "children",
        sa.Column("id", sa.BIGINT(), nullable=False),
        sa.Column("age", sa.Float(), nullable=False),
        sa.Column("birthdate", sa.Date()),
        sa.Column("person_id", sa.BIGINT(), nullable=False),
        sa.ForeignKeyConstraint(
            ["person_id"],
            ["people.id"],
            name=op.f("fk__children__person_id__people"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk__children")),
    )
    op.create_table(
        "schedule_events",
        sa.Column("id", sa.BIGINT(), nullable=False),
        sa.Column("type_event_id", sa.BIGINT(), nullable=False),
        sa.Column("theater_events_id", sa.BIGINT(), nullable=False),
        sa.Column("flag_turn_in_bot", sa.Boolean(), nullable=False),
        sa.Column(
            "datetime_event", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("qty_child", sa.BIGINT(), nullable=False),
        sa.Column("qty_child_free_seat", sa.BIGINT(), nullable=False),
        sa.Column("qty_child_nonconfirm_seat", sa.BIGINT(), nullable=False),
        sa.Column("qty_adult", sa.BIGINT(), nullable=False),
        sa.Column("qty_adult_free_seat", sa.BIGINT(), nullable=False),
        sa.Column("qty_adult_nonconfirm_seat", sa.BIGINT(), nullable=False),
        sa.Column("flag_gift", sa.Boolean(), nullable=False),
        sa.Column("flag_christmas_tree", sa.Boolean(), nullable=False),
        sa.Column("flag_santa", sa.Boolean(), nullable=False),
        sa.Column("ticket_price_type", TicketPriceTypeEnum, nullable=False),
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
            ["type_event_id"],
            ["type_events.id"],
            name=op.f("fk__schedule_events__type_event_id__type_events"),
        ),
        sa.ForeignKeyConstraint(
            ["theater_events_id"],
            ["theater_events.id"],
            name=op.f("fk__schedule_events__theater_events_id__theater_events"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk__schedule_events")),
    )
    op.create_table(
        "base_tickets",
        sa.Column("base_ticket_id", sa.BIGINT(), autoincrement=False,
                  nullable=False),
        sa.Column("flag_active", sa.Boolean(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("cost_main", sa.Numeric(), nullable=False),
        sa.Column("cost_privilege", sa.Numeric(), nullable=False),
        sa.Column(
            "period_start_change_price",
            sa.TIMESTAMP(timezone=True),
        ),
        sa.Column(
            "period_end_change_price",
            sa.TIMESTAMP(timezone=True),
        ),
        sa.Column("cost_main_in_period", sa.Numeric(), nullable=False),
        sa.Column("cost_privilege_in_period", sa.Numeric(), nullable=False),
        sa.Column("quality_of_children", sa.BIGINT(), nullable=False),
        sa.Column("quality_of_adult", sa.BIGINT(), nullable=False),
        sa.Column("quality_of_add_adult", sa.BIGINT(), nullable=False),
        sa.Column("quality_visits", sa.BIGINT(), nullable=False),
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
        sa.PrimaryKeyConstraint("base_ticket_id", name=op.f("pk__base_tickets")),
    )
    op.create_table(
        "tickets",
        sa.Column("id", sa.BIGINT(), nullable=False),
        sa.Column("base_ticket_id", sa.BIGINT(), nullable=False),
        sa.Column("price", sa.BIGINT(), nullable=False),
        sa.Column("status", TicketStatusEnum, nullable=False),
        sa.Column("schedule_event_id", sa.BIGINT()),
        sa.Column("notes", sa.String()),
        sa.Column("payment_id", sa.String()),
        sa.Column("idempotency_id", sa.String()),
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
        sa.UniqueConstraint("payment_id",
                            name=op.f("uq__tickets__payment_id")),
        sa.UniqueConstraint("idempotency_id",
                            name=op.f("uq__tickets__idempotency_id")),
        sa.ForeignKeyConstraint(
            ["schedule_event_id"],
            ["schedule_events.id"],
            name=op.f("fk__tickets__schedule_event_id__schedule_events"),
        ),
        sa.ForeignKeyConstraint(
            ["base_ticket_id"],
            ["base_tickets.base_ticket_id"],
            name=op.f("fk__tickets__base_ticket_id__base_tickets"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk__tickets")),
    )
    op.create_table(
        "people_tickets",
        sa.Column("person_id", sa.BIGINT(), nullable=False),
        sa.Column("ticket_id", sa.BIGINT(), nullable=False),
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
            ["person_id"],
            ["people.id"],
            name=op.f("fk__people_tickets__person_id__people"),
        ),
        sa.ForeignKeyConstraint(
            ["ticket_id"],
            ["tickets.id"],
            name=op.f("fk__people_tickets__ticket_id__tickets"),
        ),
        sa.PrimaryKeyConstraint(
            "person_id", "ticket_id", name=op.f("pk__people_tickets")
        ),
    )
    op.create_table(
        "users_tickets",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("ticket_id", sa.BIGINT(), nullable=False),
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
            ["ticket_id"],
            ["tickets.id"],
            name=op.f("fk__users_tickets__ticket_id__tickets"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.user_id"],
            name=op.f("fk__users_tickets__user_id__users"),
        ),
        sa.PrimaryKeyConstraint(
            "user_id", "ticket_id", name=op.f("pk__users_tickets")
        ),
    )
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table("users_tickets")
    op.drop_table("people_tickets")
    op.drop_table("tickets")
    op.drop_table("base_tickets")
    op.drop_table("schedule_events")
    op.drop_table("adults")
    op.drop_table("children")
    op.drop_table("people")
    op.drop_table("users")
    op.drop_table("type_events")
    op.drop_table("theater_events")
    TicketStatusEnum.drop(op.get_bind(), checkfirst=True)
    TicketPriceTypeEnum.drop(op.get_bind(), checkfirst=True)
    PriceTypeEnum.drop(op.get_bind(), checkfirst=True)
    AgeTypeEnum.drop(op.get_bind(), checkfirst=True)
    # ### end Alembic commands ###