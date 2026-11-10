"""Behavioral PostgreSQL RLS tests under a non-owner NOBYPASSRLS role.

The catalog test proves policies are present. This test proves the runtime role
actually sees and mutates only rows allowed by those policies.
"""
import os
import re
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import delete, insert, text
from sqlalchemy.exc import DBAPIError

from app.core.database import engine
from app.core.models import AuditEvent, Membership, Organization, Record, User


CI_RUNTIME_ROLE = os.getenv("ONECORE_CI_RLS_ROLE", "").strip()
pytestmark = pytest.mark.skipif(
    engine.dialect.name != "postgresql" or not CI_RUNTIME_ROLE,
    reason="Requires the PostgreSQL CI runtime role provisioned by onecore-ci.yml",
)


def test_runtime_role_enforces_tenant_reads_writes_and_append_only_audit(monkeypatch):
    if not re.fullmatch(r"^[a-z_][a-z0-9_]{0,62}$", CI_RUNTIME_ROLE):
        pytest.fail("ONECORE_CI_RLS_ROLE must be a safe PostgreSQL role identifier")

    from app.core.config import settings
    from app.core.runtime_role import apply_runtime_database_role

    suffix = uuid.uuid4().hex
    now = datetime.now(timezone.utc)

    with engine.begin() as connection:
        user_a_id = connection.execute(
            insert(User).values(
                email=f"rls-a-{suffix}@example.test",
                full_name="RLS tenant A",
                phone="",
                password_hash="not-a-real-login-hash",
                is_active=True,
                platform_role="customer",
                auth_version=0,
                supabase_auth_user_id=None,
                created_at=now,
            ).returning(User.id)
        ).scalar_one()
        user_b_id = connection.execute(
            insert(User).values(
                email=f"rls-b-{suffix}@example.test",
                full_name="RLS tenant B",
                phone="",
                password_hash="not-a-real-login-hash",
                is_active=True,
                platform_role="customer",
                auth_version=0,
                supabase_auth_user_id=None,
                created_at=now,
            ).returning(User.id)
        ).scalar_one()

        org_a_id = connection.execute(
            insert(Organization).values(
                name=f"RLS tenant A {suffix}",
                slug=f"rls-a-{suffix}",
                owner_user_id=user_a_id,
                industry="general",
                country="KE",
                currency="KES",
                timezone="Africa/Nairobi",
                is_active=True,
                created_at=now,
            ).returning(Organization.id)
        ).scalar_one()
        org_b_id = connection.execute(
            insert(Organization).values(
                name=f"RLS tenant B {suffix}",
                slug=f"rls-b-{suffix}",
                owner_user_id=user_b_id,
                industry="general",
                country="KE",
                currency="KES",
                timezone="Africa/Nairobi",
                is_active=True,
                created_at=now,
            ).returning(Organization.id)
        ).scalar_one()

        membership_a_id = connection.execute(
            insert(Membership).values(
                user_id=user_a_id,
                organization_id=org_a_id,
                role="org_admin",
                branch_scope="*",
                is_active=True,
            ).returning(Membership.id)
        ).scalar_one()
        membership_b_id = connection.execute(
            insert(Membership).values(
                user_id=user_b_id,
                organization_id=org_b_id,
                role="org_admin",
                branch_scope="*",
                is_active=True,
            ).returning(Membership.id)
        ).scalar_one()

        record_a_id = connection.execute(
            insert(Record).values(
                organization_id=org_a_id,
                module_key="rls-test",
                record_type="tenant-probe",
                data={"tenant": "a"},
                branch_id=None,
                created_by=user_a_id,
                created_at=now,
                updated_at=now,
            ).returning(Record.id)
        ).scalar_one()
        record_b_id = connection.execute(
            insert(Record).values(
                organization_id=org_b_id,
                module_key="rls-test",
                record_type="tenant-probe",
                data={"tenant": "b"},
                branch_id=None,
                created_by=user_b_id,
                created_at=now,
                updated_at=now,
            ).returning(Record.id)
        ).scalar_one()

        audit_a_id = connection.execute(
            insert(AuditEvent).values(
                organization_id=org_a_id,
                actor_user_id=user_a_id,
                action="rls.test",
                resource_type="tenant_probe",
                resource_id=str(record_a_id),
                detail="tenant A audit evidence",
                created_at=now,
            ).returning(AuditEvent.id)
        ).scalar_one()
        audit_b_id = connection.execute(
            insert(AuditEvent).values(
                organization_id=org_b_id,
                actor_user_id=user_b_id,
                action="rls.test",
                resource_type="tenant_probe",
                resource_id=str(record_b_id),
                detail="tenant B audit evidence",
                created_at=now,
            ).returning(AuditEvent.id)
        ).scalar_one()

        # Exercise the same transaction-local role switch used by production
        # SQLAlchemy sessions, rather than simulating the role with SQL alone.
        monkeypatch.setattr(settings, "app_env", "production")
        monkeypatch.setenv("ONECORE_DATABASE_RUNTIME_ROLE", CI_RUNTIME_ROLE)
        assert apply_runtime_database_role(connection) == CI_RUNTIME_ROLE

        role_flags = connection.execute(text("""
            SELECT current_user AS role_name,
                   r.rolsuper AS is_superuser,
                   r.rolbypassrls AS bypasses_rls
            FROM pg_roles r
            WHERE r.rolname = current_user
        """)).mappings().one()
        assert role_flags["role_name"] == CI_RUNTIME_ROLE
        assert role_flags["is_superuser"] is False
        assert role_flags["bypasses_rls"] is False

        # No organization override is set: access must be derived from the
        # authenticated user's active tenant membership.
        connection.execute(
            text("SELECT set_config('app.user_id', :user_id, true)"),
            {"user_id": str(user_a_id)},
        )

        visible_records = set(connection.execute(
            text("SELECT id FROM records WHERE id IN (:a, :b)"),
            {"a": record_a_id, "b": record_b_id},
        ).scalars().all())
        assert visible_records == {record_a_id}

        visible_memberships = set(connection.execute(
            text("SELECT id FROM memberships WHERE id IN (:a, :b)"),
            {"a": membership_a_id, "b": membership_b_id},
        ).scalars().all())
        assert visible_memberships == {membership_a_id}

        visible_audit = set(connection.execute(
            text("SELECT id FROM audit_events WHERE id IN (:a, :b)"),
            {"a": audit_a_id, "b": audit_b_id},
        ).scalars().all())
        assert visible_audit == {audit_a_id}

        assert connection.execute(
            text("SELECT count(*) FROM records WHERE organization_id = :org_id"),
            {"org_id": org_b_id},
        ).scalar_one() == 0

        # Cross-tenant writes fail closed. Savepoints keep the test transaction
        # usable after PostgreSQL rejects each statement with an RLS violation.
        with pytest.raises(DBAPIError):
            with connection.begin_nested():
                connection.execute(
                    insert(Record).values(
                        organization_id=org_b_id,
                        module_key="rls-test",
                        record_type="forbidden",
                        data={"tenant": "a"},
                        branch_id=None,
                        created_by=user_a_id,
                        created_at=now,
                        updated_at=now,
                    )
                )

        with pytest.raises(DBAPIError):
            with connection.begin_nested():
                connection.execute(
                    insert(Membership).values(
                        user_id=user_a_id,
                        organization_id=org_b_id,
                        role="staff",
                        branch_scope="*",
                        is_active=True,
                    )
                )

        with pytest.raises(DBAPIError):
            with connection.begin_nested():
                connection.execute(
                    insert(AuditEvent).values(
                        organization_id=org_b_id,
                        actor_user_id=user_a_id,
                        action="rls.test.forbidden",
                        resource_type="tenant_probe",
                        resource_id="cross-tenant",
                        detail="must be rejected",
                        created_at=now,
                    )
                )

        assert connection.execute(
            text("UPDATE records SET data = CAST(:data AS json) WHERE id = :id"),
            {"data": '{"tampered": true}', "id": record_b_id},
        ).rowcount == 0
        assert connection.execute(
            text("DELETE FROM records WHERE id = :id"),
            {"id": record_b_id},
        ).rowcount == 0

        # Audit rows are readable only in scope and are append-only even though
        # the test role has table-level UPDATE/DELETE grants.
        assert connection.execute(
            text("UPDATE audit_events SET detail = 'tampered' WHERE id = :id"),
            {"id": audit_a_id},
        ).rowcount == 0
        assert connection.execute(
            text("DELETE FROM audit_events WHERE id = :id"),
            {"id": audit_a_id},
        ).rowcount == 0

        connection.execute(text("RESET ROLE"))
        connection.execute(delete(AuditEvent).where(AuditEvent.id.in_([audit_a_id, audit_b_id])))
        connection.execute(delete(Record).where(Record.id.in_([record_a_id, record_b_id])))
        connection.execute(delete(Membership).where(Membership.id.in_([membership_a_id, membership_b_id])))
        connection.execute(delete(Organization).where(Organization.id.in_([org_a_id, org_b_id])))
        connection.execute(delete(User).where(User.id.in_([user_a_id, user_b_id])))
