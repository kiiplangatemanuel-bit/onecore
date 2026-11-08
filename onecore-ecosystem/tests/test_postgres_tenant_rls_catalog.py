"""PostgreSQL catalog assertions for tenant isolation.

These tests run against the disposable PostgreSQL 16 service in CI after Alembic
has applied the full migration chain. SQLite unit tests cannot prove RLS behavior.
"""
import pytest
from sqlalchemy import text

from app.core.database import engine


@pytest.mark.skipif(engine.dialect.name != "postgresql", reason="PostgreSQL catalog/RLS test")
def test_every_organization_owned_public_table_has_forced_rls_and_policy():
    with engine.connect() as connection:
        rows = connection.execute(text("""
            SELECT c.relname,
                   c.relrowsecurity AS rls_enabled,
                   c.relforcerowsecurity AS rls_forced,
                   EXISTS (
                       SELECT 1 FROM pg_policy p WHERE p.polrelid = c.oid
                   ) AS has_policy
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public'
              AND c.relkind IN ('r', 'p')
              AND EXISTS (
                  SELECT 1
                  FROM information_schema.columns col
                  WHERE col.table_schema = 'public'
                    AND col.table_name = c.relname
                    AND col.column_name = 'organization_id'
              )
            ORDER BY c.relname
        """)).mappings().all()

    assert rows, "Expected tenant-owned public tables after migrations"
    unsafe = [
        row["relname"] for row in rows
        if not row["rls_enabled"] or not row["rls_forced"] or not row["has_policy"]
    ]
    assert not unsafe, (
        "Every public table with organization_id must ENABLE and FORCE RLS "
        f"and have at least one policy; unsafe tables: {unsafe}"
    )
