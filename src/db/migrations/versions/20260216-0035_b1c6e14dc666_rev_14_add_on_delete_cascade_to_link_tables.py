"""rev_14: add ON DELETE CASCADE to link tables

Revision ID: b1c6e14dc666
Revises: 7a9b2c1d3e4f
Create Date: 2026-02-16 00:35:00.000000

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "b1c6e14dc666"
down_revision = "7a9b2c1d3e4f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- users_tickets ---
    op.drop_constraint(
        op.f("fk__users_tickets__user_id__users"),
        "users_tickets",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk__users_tickets__ticket_id__tickets"),
        "users_tickets",
        type_="foreignkey",
    )
    op.create_foreign_key(
        op.f("fk__users_tickets__user_id__users"),
        "users_tickets",
        "users",
        ["user_id"],
        ["user_id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        op.f("fk__users_tickets__ticket_id__tickets"),
        "users_tickets",
        "tickets",
        ["ticket_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # --- people_tickets ---
    op.drop_constraint(
        op.f("fk__people_tickets__person_id__people"),
        "people_tickets",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk__people_tickets__ticket_id__tickets"),
        "people_tickets",
        type_="foreignkey",
    )
    op.create_foreign_key(
        op.f("fk__people_tickets__person_id__people"),
        "people_tickets",
        "people",
        ["person_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        op.f("fk__people_tickets__ticket_id__tickets"),
        "people_tickets",
        "tickets",
        ["ticket_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    # --- people_tickets ---
    op.drop_constraint(
        op.f("fk__people_tickets__ticket_id__tickets"),
        "people_tickets",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk__people_tickets__person_id__people"),
        "people_tickets",
        type_="foreignkey",
    )
    op.create_foreign_key(
        op.f("fk__people_tickets__person_id__people"),
        "people_tickets",
        "people",
        ["person_id"],
        ["id"],
    )
    op.create_foreign_key(
        op.f("fk__people_tickets__ticket_id__tickets"),
        "people_tickets",
        "tickets",
        ["ticket_id"],
        ["id"],
    )

    # --- users_tickets ---
    op.drop_constraint(
        op.f("fk__users_tickets__ticket_id__tickets"),
        "users_tickets",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk__users_tickets__user_id__users"),
        "users_tickets",
        type_="foreignkey",
    )
    op.create_foreign_key(
        op.f("fk__users_tickets__ticket_id__tickets"),
        "users_tickets",
        "tickets",
        ["ticket_id"],
        ["id"],
    )
    op.create_foreign_key(
        op.f("fk__users_tickets__user_id__users"),
        "users_tickets",
        "users",
        ["user_id"],
        ["user_id"],
    )
