from alembic import context
from sqlalchemy import engine_from_config, pool, text
from app.core.config import settings
from app.core.database import Base, normalized_database_url
from app.core import models  # noqa: F401 - register all mapped tables
from app.core import inventory_models  # noqa: F401 - register extended inventory tables
from app.core import procurement_workflow_models  # noqa: F401 - register procurement workflow tables
from app.core import pos_completion_models  # noqa: F401 - register POS completion tables
from app.core import hr_payroll_models  # noqa: F401 - register HR/payroll tables
from app.core import finance_ops_models  # noqa: F401 - register FX and statutory remittance tables
from app.core import identity_models  # noqa: F401 - register account session and portal assurance tables
from app.core import sacco_models  # noqa: F401 - register SACCO membership tables

config = context.config
database_url = str(normalized_database_url(settings.alembic_connection_url))
config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
target_metadata = Base.metadata


def run_migrations_offline():
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        # Alembic's default version_num is VARCHAR(32), but this repository has
        # historical revision identifiers longer than 32 characters. SQLite
        # does not enforce VARCHAR length, while PostgreSQL does. Widen/create
        # the version table before Alembic records any revision on PostgreSQL.
        if connection.dialect.name == "postgresql":
            connection.execute(text(
                "CREATE TABLE IF NOT EXISTS alembic_version "
                "(version_num VARCHAR(255) NOT NULL PRIMARY KEY)"
            ))
            connection.execute(text(
                "ALTER TABLE alembic_version "
                "ALTER COLUMN version_num TYPE VARCHAR(255)"
            ))
            connection.commit()
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
