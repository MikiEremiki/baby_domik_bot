"""rev_13: add user_statuses table

Revision ID: 7a9b2c1d3e4f
Revises: 105f2aad266f
Create Date: 2026-02-04 18:09:12.123456

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from db import BaseModel

# revision identifiers, used by Alembic.
revision = "7a9b2c1d3e4f"
down_revision = "105f2aad266f"
branch_labels = None
depends_on = None

UserRoleEnum = sa.Enum(
    "USER",
    "ADMIN",
    "DEVELOPER",
    "SUPERUSER",
    name="userrole",
    metadata=BaseModel.metadata
)


def upgrade() -> None:
    UserRoleEnum.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "user_statuses",
        sa.Column("user_id", sa.BIGINT(), nullable=False),
        sa.Column("role", UserRoleEnum, nullable=False, server_default="USER"),
        sa.Column("is_blocked_by_user", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_blacklisted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_blocked_by_admin", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("blocked_by_admin_id", sa.BIGINT(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk__user_statuses")),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], name=op.f("fk__user_statuses__user_id__users"), ondelete="CASCADE"),
    )


def downgrade() -> None:
    op.drop_table("user_statuses")
    UserRoleEnum.drop(op.get_bind(), checkfirst=True)
