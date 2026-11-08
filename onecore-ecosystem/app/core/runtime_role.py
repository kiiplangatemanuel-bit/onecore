"""Enforce a least-privilege PostgreSQL role for every application transaction.

Set ONECORE_DATABASE_RUNTIME_ROLE to a pre-provisioned NOBYPASSRLS role.
The login role must be a member of that role; migrations must run separately
with a migration-owner credential and must never use the runtime URL.
"""
import os
import re

from sqlalchemy import event, text
from sqlalchemy.orm import Session

from app.core.config import settings

_ROLE_PATTERN = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def apply_runtime_database_role(connection) -> str | None:
    if connection.dialect.name != "postgresql":
        return None
    environment = settings.app_env.strip().lower()
    if environment not in {"production", "prod"}:
        return None
    role = os.getenv("ONECORE_DATABASE_RUNTIME_ROLE", "").strip()
    if not role or not _ROLE_PATTERN.fullmatch(role):
        raise RuntimeError(
            "ONECORE_DATABASE_RUNTIME_ROLE must name a pre-provisioned least-privilege PostgreSQL role"
        )
    # The strict identifier allowlist makes identifier quoting safe. SET LOCAL
    # is transaction-scoped, so pooled connections cannot leak a role to the
    # next request and rollback automatically restores the login role.
    connection.execute(text(f'SET LOCAL ROLE "{role}"'))
    actual = connection.execute(text("SELECT current_user")).scalar_one()
    if actual != role:
        raise RuntimeError("PostgreSQL did not assume the configured runtime role")
    flags = connection.execute(text("""
        SELECT r.rolsuper AS is_superuser, r.rolbypassrls AS bypasses_rls
        FROM pg_roles r WHERE r.rolname = current_user
    """)).mappings().one_or_none()
    if not flags or flags["is_superuser"] or flags["bypasses_rls"]:
        raise RuntimeError("Runtime database role must be a non-superuser NOBYPASSRLS role")
    return role


@event.listens_for(Session, "after_begin")
def _assume_runtime_database_role(session, transaction, connection):
    apply_runtime_database_role(connection)
