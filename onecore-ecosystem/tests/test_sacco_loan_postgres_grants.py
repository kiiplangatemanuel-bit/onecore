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
            "sacco_loan_installments", "sacco_loan_disbursements",
            "sacco_loan_repayments", "sacco_loan_repayment_allocations",
            "sacco_loan_repayment_journal_lines",
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

        for table in (
            "sacco_loan_products", "sacco_loan_installments", "sacco_loan_disbursements",
            "sacco_loan_repayments", "sacco_loan_repayment_allocations",
            "sacco_loan_repayment_journal_lines",
        ):
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


def test_sacco_loan_disbursement_grants_are_column_scoped():
    with engine.connect() as connection:
        assert connection.execute(text(
            "SELECT has_table_privilege('onecore_api', 'public.sacco_loan_disbursements', 'UPDATE')"
        )).scalar_one() is False
        assert connection.execute(text("""
            SELECT has_column_privilege(
                'onecore_api', 'public.sacco_loan_disbursements', 'status', 'UPDATE'
            )
        """)).scalar_one() is True
        assert connection.execute(text("""
            SELECT has_column_privilege(
                'onecore_api', 'public.sacco_loan_disbursements', 'reviewed_by', 'UPDATE'
            )
        """)).scalar_one() is True
        assert connection.execute(text("""
            SELECT has_column_privilege(
                'onecore_api', 'public.sacco_loan_disbursements', 'external_reference', 'UPDATE'
            )
        """)).scalar_one() is False
        assert connection.execute(text("""
            SELECT has_column_privilege(
                'onecore_api', 'public.sacco_loan_installments', 'status', 'UPDATE'
            )
        """)).scalar_one() is True



def test_sacco_loan_repayment_grants_allow_only_review_columns_and_insert_only_ledgers():
    with engine.connect() as connection:
        assert connection.execute(text(
            "SELECT has_table_privilege('onecore_api', 'public.sacco_loan_repayments', 'UPDATE')"
        )).scalar_one() is False
        for column in ("status", "reviewed_by", "reviewed_at", "review_note"):
            assert connection.execute(text("""
                SELECT has_column_privilege(
                    'onecore_api', 'public.sacco_loan_repayments', :column, 'UPDATE'
                )
            """), {"column": column}).scalar_one() is True
        for column in ("amount", "external_reference", "requested_by", "idempotency_key"):
            assert connection.execute(text("""
                SELECT has_column_privilege(
                    'onecore_api', 'public.sacco_loan_repayments', :column, 'UPDATE'
                )
            """), {"column": column}).scalar_one() is False

        for table in ("sacco_loan_repayment_allocations", "sacco_loan_repayment_journal_lines"):
            assert connection.execute(text(
                "SELECT has_table_privilege('onecore_api', :table, 'UPDATE')"
            ), {"table": f"public.{table}"}).scalar_one() is False
            assert connection.execute(text(
                "SELECT has_table_privilege('onecore_api', :table, 'DELETE')"
            ), {"table": f"public.{table}"}).scalar_one() is False

        for column in ("principal_paid", "interest_paid", "status"):
            assert connection.execute(text("""
                SELECT has_column_privilege(
                    'onecore_api', 'public.sacco_loan_installments', :column, 'UPDATE'
                )
            """), {"column": column}).scalar_one() is True
        assert connection.execute(text("""
            SELECT has_column_privilege(
                'onecore_api', 'public.sacco_loan_installments', 'total_due', 'UPDATE'
            )
        """)).scalar_one() is False
