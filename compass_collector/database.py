from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from compass_collector.config.settings import DATABASE_URL

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {},
    pool_pre_ping=True
)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def init_db():
    Base.metadata.create_all(bind=engine)
    migrate_schema()


def migrate_schema():
    inspector = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            existing = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing:
                    continue
                if not column.nullable and (column.default is None or not column.default.is_scalar):
                    raise RuntimeError(
                        f"Cannot add NOT NULL column {table.name}.{column.name} without a scalar default"
                    )
                col_type = column.type.compile(engine.dialect)
                stmt = f"ALTER TABLE {table.name} ADD COLUMN {column.name} {col_type}"
                if column.default is not None and column.default.is_scalar:
                    literal = column.type.literal_processor(engine.dialect)
                    if literal is not None:
                        stmt += f" DEFAULT {literal(column.default.arg)}"
                conn.execute(text(stmt))


def get_session():
    return SessionLocal()
