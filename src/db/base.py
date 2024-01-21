from datetime import datetime

from sqlalchemy import BIGINT, TIMESTAMP, MetaData, sql
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, registry


# https://alembic.sqlalchemy.org/en/latest/naming.html
convention = {
    'all_column_names': lambda constraint, table: '_'.join([
        column.name for column in constraint.columns.values()
    ]),
    'ix': 'ix__%(table_name)s__%(all_column_names)s',
    'uq': 'uq__%(table_name)s__%(all_column_names)s',
    'ck': 'ck__%(table_name)s__%(constraint_name)s',
    'fk': (
        'fk__%(table_name)s__%(all_column_names)s__'
        '%(referred_table_name)s'
    ),
    'pk': 'pk__%(table_name)s'
}

type_annotation_map = {
        int: BIGINT,
        datetime: TIMESTAMP(timezone=True),
    }

mapper_registry = registry(metadata=MetaData(naming_convention=convention),
                           type_annotation_map=type_annotation_map)


class BaseModel(DeclarativeBase):
    registry = mapper_registry
    metadata = mapper_registry.metadata


class BaseModelTimed(BaseModel):
    """
    An abstract base model that adds created_at and updated_at timestamp fields to the model
    """
    __abstract__ = True

    created_at: Mapped[datetime] = mapped_column(
        nullable=False,
        server_default=sql.func.now())
    updated_at: Mapped[datetime] = mapped_column(
        nullable=False,
        server_default=sql.func.now(),
        onupdate=sql.func.now(),
    )
