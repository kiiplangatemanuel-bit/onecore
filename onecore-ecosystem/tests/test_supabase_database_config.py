from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_supabase_postgres_url_schemes_are_normalized_to_psycopg():
    legacy = Settings(_env_file=None, database_url="postgres://user:pass@db.example/postgres?sslmode=require")
    standard = Settings(_env_file=None, database_url="postgresql://user:pass@db.example/postgres?sslmode=require")
    explicit = Settings(_env_file=None, database_url="postgresql+psycopg://user:pass@db.example/postgres?sslmode=require")
    assert legacy.database_url.startswith("postgresql+psycopg://")
    assert standard.database_url.startswith("postgresql+psycopg://")
    assert explicit.database_url.startswith("postgresql+psycopg://")


def test_production_requires_tls_postgres_database_url():
    safe = dict(
        app_env="production",
        debug=False,
        secret_key="s" * 48,
        database_url="postgresql+psycopg://user:pass@db.example/postgres?sslmode=require",
        cors_origins="https://app.example.com",
        trusted_hosts="api.example.com",
        force_https=True,
    )
    Settings(_env_file=None, **safe)
    with pytest.raises(ValidationError, match="sslmode=require"):
        Settings(_env_file=None, **{**safe, "database_url": "postgresql+psycopg://user:pass@db.example/postgres"})
    with pytest.raises(ValidationError, match="managed PostgreSQL"):
        Settings(_env_file=None, **{**safe, "database_url": "sqlite:///./onecore.db"})


def test_react_procurement_workspace_is_mounted_and_api_backed():
    root = Path(__file__).resolve().parents[2]
    component = (root / "frontend" / "src" / "ProcurementWorkspace.jsx").read_text(encoding="utf-8")
    app = (root / "frontend" / "src" / "App.jsx").read_text(encoding="utf-8")
    for endpoint in (
        "/api/v1/procurement/suppliers",
        "/api/v1/procurement/orders",
        "/api/v1/procurement/requisitions",
        "/api/v1/procurement/goods-receipts",
        "/api/v1/procurement/supplier-settlements",
        "/api/v1/procurement/accounting-reconciliation",
    ):
        assert endpoint in component
    assert 'path==="/procurement"?<ProcurementWorkspace' in app
