"""Shared SQLAlchemy database engine.

Production deployments use Supabase's managed PostgreSQL. The application accesses
Supabase Postgres through SQLAlchemy so all existing domain models and Alembic
migrations use the same durable database; the browser never receives DB credentials.
"""
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings


def normalized_database_url(value: str):
    """Return a psycopg 3 URL and require TLS for Supabase connections."""
    url = make_url(value)
    if url.get_backend_name() == "postgresql" and url.drivername in {"postgres", "postgresql"}:
        url = url.set(drivername="postgresql+psycopg")
    host = (url.host or "").lower()
    if host.endswith(".supabase.co") or host.endswith(".pooler.supabase.com"):
        query = dict(url.query)
        if query.get("sslmode", "").lower() not in {"require", "verify-ca", "verify-full"}:
            query["sslmode"] = "require"
        url = url.set(query=query)
    return url


DATABASE_URL = normalized_database_url(settings.database_connection_url)
_is_sqlite = DATABASE_URL.get_backend_name() == "sqlite"
_is_transaction_pooler = (
    DATABASE_URL.get_backend_name() == "postgresql"
    and (DATABASE_URL.host or "").lower().endswith(".pooler.supabase.com")
    and DATABASE_URL.port == 6543
)

connect_args = {"check_same_thread": False} if _is_sqlite else {}
if not _is_sqlite:
    connect_args["application_name"] = "onecore-api"
    # Supabase transaction-mode PgBouncer cannot safely retain server-side
    # prepared statements between transactions.
    if _is_transaction_pooler:
        connect_args["prepare_threshold"] = None

engine_options = {"pool_pre_ping": True}
if not _is_sqlite:
    engine_options.update(
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_recycle=settings.database_pool_recycle_seconds,
        pool_timeout=30,
        pool_use_lifo=True,
    )

engine = create_engine(DATABASE_URL, connect_args=connect_args, **engine_options)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
