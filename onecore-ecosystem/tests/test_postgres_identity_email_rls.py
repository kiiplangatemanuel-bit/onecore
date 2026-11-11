"""Exercise account-owned identity email RLS with separate API and worker roles."""
import os
import re
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, insert, text
from sqlalchemy.exc import DBAPIError

from app.core.database import engine
from app.core.identity_models import IdentityEmailDelivery
from app.core.models import User

CI_RUNTIME_ROLE = os.getenv("ONECORE_CI_RLS_ROLE", "").strip()
WORKER_ROLE = "onecore_identity_email_worker"
pytestmark = pytest.mark.skipif(
    engine.dialect.name != "postgresql" or not CI_RUNTIME_ROLE,
    reason="Requires PostgreSQL API and identity-email worker roles from onecore-ci.yml",
)


def test_identity_email_outbox_is_account_scoped_and_worker_managed(monkeypatch):
    if not re.fullmatch(r"^[a-z_][a-z0-9_]{0,62}$", CI_RUNTIME_ROLE):
        pytest.fail("ONECORE_CI_RLS_ROLE must be a safe PostgreSQL role identifier")

    from app.core.config import settings
    from app.core.runtime_role import apply_runtime_database_role

    suffix = uuid.uuid4().hex
    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=30)
    with engine.begin() as connection:
        user_a_id = connection.execute(
            insert(User).values(
                email=f"identity-a-{suffix}@example.test",
                full_name="Identity A",
                phone="",
                password_hash="not-a-login-hash",
                is_active=True,
                platform_role="customer",
                auth_version=0,
                supabase_auth_user_id=None,
                created_at=now,
            ).returning(User.id)
        ).scalar_one()
        user_b_id = connection.execute(
            insert(User).values(
                email=f"identity-b-{suffix}@example.test",
                full_name="Identity B",
                phone="",
                password_hash="not-a-login-hash",
                is_active=True,
                platform_role="customer",
                auth_version=0,
                supabase_auth_user_id=None,
                created_at=now,
            ).returning(User.id)
        ).scalar_one()
        delivery_a_id = connection.execute(
            insert(IdentityEmailDelivery).values(
                user_id=user_a_id,
                purpose="password_reset",
                event_key=f"password-reset-a:{suffix}",
                payload_ciphertext="ciphertext-a",
                status="pending",
                attempts=0,
                next_attempt_at=now,
                expires_at=expires,
                last_error="",
                created_at=now,
                updated_at=now,
            ).returning(IdentityEmailDelivery.id)
        ).scalar_one()
        delivery_b_id = connection.execute(
            insert(IdentityEmailDelivery).values(
                user_id=user_b_id,
                purpose="password_reset",
                event_key=f"password-reset-b:{suffix}",
                payload_ciphertext="ciphertext-b",
                status="pending",
                attempts=0,
                next_attempt_at=now,
                expires_at=expires,
                last_error="",
                created_at=now,
                updated_at=now,
            ).returning(IdentityEmailDelivery.id)
        ).scalar_one()

        monkeypatch.setattr(settings, "app_env", "production")
        monkeypatch.setenv("ONECORE_DATABASE_RUNTIME_ROLE", CI_RUNTIME_ROLE)
        assert apply_runtime_database_role(connection) == CI_RUNTIME_ROLE
        flags = connection.execute(text("""
            SELECT current_user AS role_name,
                   r.rolsuper AS is_superuser,
                   r.rolbypassrls AS bypasses_rls
            FROM pg_roles r WHERE r.rolname = current_user
        """)).mappings().one()
        assert flags["role_name"] == CI_RUNTIME_ROLE
        assert flags["is_superuser"] is False
        assert flags["bypasses_rls"] is False
        connection.execute(
            text("SELECT set_config('app.user_id', :user_id, true)"),
            {"user_id": str(user_a_id)},
        )
        visible = set(connection.execute(
            text("SELECT id FROM identity_email_deliveries")
        ).scalars().all())
        assert visible == {delivery_a_id}

        with pytest.raises(DBAPIError):
            with connection.begin_nested():
                connection.execute(
                    insert(IdentityEmailDelivery).values(
                        user_id=user_b_id,
                        purpose="password_reset",
                        event_key=f"forbidden:{suffix}",
                        payload_ciphertext="ciphertext",
                        status="pending",
                        attempts=0,
                        next_attempt_at=now,
                        expires_at=expires,
                        last_error="",
                        created_at=now,
                        updated_at=now,
                    )
                )

        with pytest.raises(DBAPIError):
            with connection.begin_nested():
                connection.execute(
                    text("UPDATE identity_email_deliveries SET status = 'delivered' WHERE id = :id"),
                    {"id": delivery_a_id},
                )

        connection.execute(text("RESET ROLE"))
        connection.execute(text(f'SET LOCAL ROLE "{WORKER_ROLE}"'))
        worker_flags = connection.execute(text("""
            SELECT current_user AS role_name,
                   r.rolsuper AS is_superuser,
                   r.rolbypassrls AS bypasses_rls
            FROM pg_roles r WHERE r.rolname = current_user
        """)).mappings().one()
        assert worker_flags["role_name"] == WORKER_ROLE
        assert worker_flags["is_superuser"] is False
        assert worker_flags["bypasses_rls"] is False
        worker_visible = set(connection.execute(
            text("SELECT id FROM identity_email_deliveries")
        ).scalars().all())
        assert worker_visible == {delivery_a_id, delivery_b_id}
        assert connection.execute(
            text("UPDATE identity_email_deliveries SET status = 'delivered' WHERE id = :id"),
            {"id": delivery_a_id},
        ).rowcount == 1

        connection.execute(text("RESET ROLE"))
        connection.execute(
            delete(IdentityEmailDelivery).where(
                IdentityEmailDelivery.id.in_([delivery_a_id, delivery_b_id])
            )
        )
        connection.execute(delete(User).where(User.id.in_([user_a_id, user_b_id])))
