"""Test session setup: ensure the default fixture database schema is migrated
to match the current SQLAlchemy models AND receives the same legacy backfill
applied to production (migration 2026-08-14).

Production ran: schema ALTER + UPDATE publication_status='published',
verification_status='legacy' for all legacy records. Tests using the default
engine must reflect the same state so the retrieval gate
(publication_status == 'published') behaves identically.
"""
import pytest

from compass_collector.database import engine, init_db, migrate_schema
from sqlalchemy import text


@pytest.fixture(scope="session", autouse=True)
def migrate_default_db():
    init_db()  # create_all + migrate_schema (adds governance columns if missing)
    with engine.begin() as conn:
        # Legacy backfill — mirrors production migration:
        # all pre-existing records become published + legacy.
        conn.execute(text(
            "UPDATE intervention_records SET publication_status='published', "
            "verification_status='legacy' "
            "WHERE publication_status IS NULL OR publication_status='staging'"
        ))
    yield
