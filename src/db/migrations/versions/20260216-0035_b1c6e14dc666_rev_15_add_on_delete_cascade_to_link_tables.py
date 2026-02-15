from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "b1c6e14dc666"
down_revision = "c00ba0fb22b5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- users_tickets ---
    op.drop_constraint(
        "fk__users_tickets__user_id__users",
        "users_tickets",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk__users_tickets__ticket_id__tickets",
        "users_tickets",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk__users_tickets__user_id__users",
        "users_tickets",
        "users",
        ["user_id"],
        ["user_id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk__users_tickets__ticket_id__tickets",
        "users_tickets",
        "tickets",
        ["ticket_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # --- people_tickets ---
    op.drop_constraint(
        "fk__people_tickets__person_id__people",
        "people_tickets",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk__people_tickets__ticket_id__tickets",
        "people_tickets",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk__people_tickets__person_id__people",
        "people_tickets",
        "people",
        ["person_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk__people_tickets__ticket_id__tickets",
        "people_tickets",
        "tickets",
        ["ticket_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    # --- people_tickets ---
    op.drop_constraint(
        "fk__people_tickets__ticket_id__tickets",
        "people_tickets",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk__people_tickets__person_id__people",
        "people_tickets",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk__people_tickets__person_id__people",
        "people_tickets",
        "people",
        ["person_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk__people_tickets__ticket_id__tickets",
        "people_tickets",
        "tickets",
        ["ticket_id"],
        ["id"],
    )

    # --- users_tickets ---
    op.drop_constraint(
        "fk__users_tickets__ticket_id__tickets",
        "users_tickets",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk__users_tickets__user_id__users",
        "users_tickets",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk__users_tickets__ticket_id__tickets",
        "users_tickets",
        "tickets",
        ["ticket_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk__users_tickets__user_id__users",
        "users_tickets",
        "users",
        ["user_id"],
        ["user_id"],
    )
