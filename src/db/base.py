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

    repr_cols_num = 1
    repr_cols = tuple()

    def __repr__(self):
        cols = []
        for idx, col in enumerate(self.__table__.columns.keys()):
            if col in self.repr_cols or idx < self.repr_cols_num:
                cols.append(f'{col}={getattr(self, col)}')
        return f"({self.__class__.__name__} {', '.join(cols)})"

    def model_dump(self):
        model_dump = {}
        for col in self.__table__.columns.keys():
            model_dump[col] = getattr(self, col)
        return model_dump


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
