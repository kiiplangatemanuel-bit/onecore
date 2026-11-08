import pytest


class _Scalar:
    def __init__(self, value):
        self.value = value

    def scalar_one(self):
        return self.value

    def mappings(self):
        return self

    def one_or_none(self):
        return self.value


class _RoleConnection:
    class dialect:
        name = "postgresql"

    def __init__(self, role="onecore_api", superuser=False, bypass=False):
        self.role = role
        self.superuser = superuser
        self.bypass = bypass
        self.statements = []

    def execute(self, statement):
        sql = str(statement)
        self.statements.append(sql)
        if "SELECT current_user" in sql:
            return _Scalar(self.role)
        if "FROM pg_roles" in sql:
            return _Scalar({
                "is_superuser": self.superuser,
                "bypasses_rls": self.bypass,
            } if self.role else None)
        return _Scalar(None)


def test_runtime_role_is_applied_transaction_locally(monkeypatch):
    from app.core.runtime_role import apply_runtime_database_role
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("ONECORE_DATABASE_RUNTIME_ROLE", "onecore_api")
    connection = _RoleConnection()
    assert apply_runtime_database_role(connection) == "onecore_api"
    assert 'SET LOCAL ROLE "onecore_api"' in connection.statements


@pytest.mark.parametrize("role", ["", "postgres; DROP ROLE postgres", "UpperCase", "role name"])
def test_runtime_role_rejects_missing_or_unsafe_identifiers(monkeypatch, role):
    from app.core.runtime_role import apply_runtime_database_role
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("ONECORE_DATABASE_RUNTIME_ROLE", role)
    with pytest.raises(RuntimeError, match="ONECORE_DATABASE_RUNTIME_ROLE"):
        apply_runtime_database_role(_RoleConnection())


@pytest.mark.parametrize("superuser,bypass", [(True, False), (False, True)])
def test_runtime_role_rejects_privileged_effective_role(monkeypatch, superuser, bypass):
    from app.core.runtime_role import apply_runtime_database_role
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("ONECORE_DATABASE_RUNTIME_ROLE", "onecore_api")
    with pytest.raises(RuntimeError, match="NOBYPASSRLS"):
        apply_runtime_database_role(_RoleConnection(superuser=superuser, bypass=bypass))


def test_runtime_role_is_not_applied_outside_production(monkeypatch):
    from app.core.runtime_role import apply_runtime_database_role
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("ONECORE_DATABASE_RUNTIME_ROLE", raising=False)
    assert apply_runtime_database_role(_RoleConnection()) is None
