"""PostgreSQL checks for the SACCO loan API's column-level grants."""
import pytest
from sqlalchemy import text

from app.core.database import engine

pytestmark = pytest.mark.skipif(
    engine.dialect.name != "postgresql",
    reason="Requires PostgreSQL role and column-privilege catalogs",
)


def test_sacco_loan_api_role_is_nobypassrls_and_has_only_workflow_column_updates():
    with engine.connect() as connection:
        role = connection.execute(text("""
            SELECT rolsuper, rolbypassrls, rolcanlogin
            FROM pg_roles WHERE rolname = 'onecore_api'
        """)).one_or_none()
        assert role is not None
        assert role.rolsuper is False
        assert role.rolbypassrls is False
        assert role.rolcanlogin is False

        tables = (
            "sacco_loan_products", "sacco_loan_applications",
            "sacco_loan_guarantors", "sacco_loan_collateral",
            "sacco_loan_installments",
        )
        for table in tables:
            assert connection.execute(text(
                "SELECT has_table_privilege('onecore_api', :table, 'SELECT')"
            ), {"table": f"public.{table}"}).scalar_one() is True
            assert connection.execute(text(
                "SELECT has_table_privilege('onecore_api', :table, 'INSERT')"
            ), {"table": f"public.{table}"}).scalar_one() is True
            assert connection.execute(text(
                "SELECT has_table_privilege('onecore_api', :table, 'DELETE')"
            ), {"table": f"public.{table}"}).scalar_one() is False

        for table in ("sacco_loan_products", "sacco_loan_installments"):
            assert connection.execute(text(
                "SELECT has_table_privilege('onecore_api', :table, 'UPDATE')"
            ), {"table": f"public.{table}"}).scalar_one() is False

        assert connection.execute(text(
            "SELECT has_table_privilege('onecore_api', 'public.sacco_loan_applications', 'UPDATE')"
        )).scalar_one() is False
        assert connection.execute(text("""
            SELECT has_column_privilege(
                'onecore_api', 'public.sacco_loan_applications', 'status', 'UPDATE'
            )
        """)).scalar_one() is True
        assert connection.execute(text("""
            SELECT has_column_privilege(
                'onecore_api', 'public.sacco_loan_applications', 'principal', 'UPDATE'
            )
        """)).scalar_one() is False
        assert connection.execute(text("""
            SELECT has_column_privilege(
                'onecore_api', 'public.sacco_loan_guarantors', 'consent_status', 'UPDATE'
            )
        """)).scalar_one() is True
        assert connection.execute(text("""
            SELECT has_column_privilege(
                'onecore_api', 'public.sacco_loan_guarantors', 'guaranteed_amount', 'UPDATE'
            )
        """)).scalar_one() is False
        assert connection.execute(text("""
            SELECT has_column_privilege(
                'onecore_api', 'public.sacco_loan_collateral', 'status', 'UPDATE'
            )
        """)).scalar_one() is True
        assert connection.execute(text("""
            SELECT has_column_privilege(
                'onecore_api', 'public.sacco_loan_collateral', 'declared_value', 'UPDATE'
            )
        """)).scalar_one() is False
