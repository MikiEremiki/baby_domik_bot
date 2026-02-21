"""rev_18: add promotions

Revision ID: 8d8e8b8c8a89
Revises: c427f0da1b22
Create Date: 2026-02-20 21:40:00.000000

"""
from alembic import op
import sqlalchemy as sa

from db import BaseModel

# revision identifiers, used by Alembic.
revision = "8d8e8b8c8a89"
down_revision = "c427f0da1b22"
branch_labels = None
depends_on = None

GroupOfPeopleByDiscountTypeEnum = sa.Enum(
    "all",
    "privilege",
    "non_privilege",
    name="group_of_people_by_discount_type",
    metadata=BaseModel.metadata
)

PromotionDiscountTypeEnum = sa.Enum(
    "percentage",
    "fixed",
    name="promotion_discount_type",
    metadata=BaseModel.metadata
)


def upgrade() -> None:
    # 1. Create Enums
    PromotionDiscountTypeEnum.create(op.get_bind(), checkfirst=True)
    GroupOfPeopleByDiscountTypeEnum.create(op.get_bind(), checkfirst=True)

    # 2. Create promotions table
    op.create_table(
        "promotions",
        sa.Column("id", sa.BIGINT(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("discount", sa.BIGINT(), nullable=False),
        sa.Column(
            "discount_type",
            PromotionDiscountTypeEnum,
            nullable=False,
            server_default="fixed",
        ),
        sa.Column("start_date", sa.TIMESTAMP(timezone=True)),
        sa.Column("expire_date", sa.TIMESTAMP(timezone=True)),
        sa.Column(
            "for_who_discount",
            GroupOfPeopleByDiscountTypeEnum,
            nullable=False
        ),
        sa.Column("flag_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "is_visible_as_option",
            sa.Boolean(),
            nullable=False,
            server_default="false"
        ),
        sa.Column("count_of_usage", sa.BIGINT(), nullable=False, server_default="0"),
        sa.Column("max_count_of_usage", sa.BIGINT(), nullable=False, server_default="0"),
        sa.Column("max_usage_per_user", sa.BIGINT(), nullable=False, server_default="0"),
        sa.Column("min_purchase_sum", sa.BIGINT(), nullable=False, server_default="0"),
        sa.Column("description_user", sa.String(), nullable=True),
        sa.Column(
            "requires_verification",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
        sa.Column("verification_text", sa.String(), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk__promotions")),
        sa.UniqueConstraint("code", name=op.f("uq__promotions__code")),
    )

    # 3. Add promo_id to tickets
    op.add_column("tickets", sa.Column("promo_id", sa.BIGINT(), nullable=True))
    op.create_foreign_key(
        op.f("fk__tickets__promo_id__promotions"),
        "tickets",
        "promotions",
        ["promo_id"],
        ["id"],
    )

    # 4. Create junction tables
    op.create_table(
        "promotions_type_events",
        sa.Column("promotion_id", sa.BIGINT(), nullable=False),
        sa.Column("type_event_id", sa.BIGINT(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["promotion_id"], ["promotions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["type_event_id"], ["type_events.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("promotion_id", "type_event_id")
    )
    op.create_table(
        "promotions_theater_events",
        sa.Column("promotion_id", sa.BIGINT(), nullable=False),
        sa.Column("theater_event_id", sa.BIGINT(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["promotion_id"], ["promotions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["theater_event_id"], ["theater_events.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("promotion_id", "theater_event_id")
    )
    op.create_table(
        "promotions_base_tickets",
        sa.Column("promotion_id", sa.BIGINT(), nullable=False),
        sa.Column("base_ticket_id", sa.BIGINT(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["promotion_id"], ["promotions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["base_ticket_id"],
            ["base_tickets.base_ticket_id"],
            ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("promotion_id", "base_ticket_id")
    )
    op.create_table(
        "promotions_schedule_events",
        sa.Column("promotion_id", sa.BIGINT(), nullable=False),
        sa.Column("schedule_event_id", sa.BIGINT(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["promotion_id"], ["promotions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["schedule_event_id"], ["schedule_events.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("promotion_id", "schedule_event_id")
    )


def downgrade() -> None:
    # 1. Drop junction tables
    op.drop_table("promotions_schedule_events")
    op.drop_table("promotions_base_tickets")
    op.drop_table("promotions_theater_events")
    op.drop_table("promotions_type_events")

    # 2. Remove promo_id from tickets
    op.drop_constraint(
        op.f("fk__tickets__promo_id__promotions"),
        "tickets",
        type_="foreignkey"
    )
    op.drop_column("tickets", "promo_id")

    # 3. Drop promotions table
    op.drop_table("promotions")

    # 4. Drop Enum
    PromotionDiscountTypeEnum.drop(op.get_bind(), checkfirst=True)
    GroupOfPeopleByDiscountTypeEnum.drop(op.get_bind(), checkfirst=True)
