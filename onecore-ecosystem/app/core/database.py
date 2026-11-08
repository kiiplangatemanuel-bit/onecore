from urllib.parse import urlparse

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import NullPool

from app.core.config import settings


database_url = settings.database_url
parsed_url = urlparse(database_url)
is_supabase_transaction_pooler = (
    (parsed_url.hostname or "").endswith(".pooler.supabase.com")
    and parsed_url.port == 6543
)

connect_args = {}
if database_url.startswith("sqlite"):
    connect_args["check_same_thread"] = False
elif is_supabase_transaction_pooler:
    # PgBouncer transaction mode cannot safely retain prepared statements.
    connect_args["prepare_threshold"] = None

engine_options = {"connect_args": connect_args, "pool_pre_ping": True}
if is_supabase_transaction_pooler:
    engine_options["poolclass"] = NullPool

engine = create_engine(database_url, **engine_options)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
