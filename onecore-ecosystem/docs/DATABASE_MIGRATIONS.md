# Database schema migrations

OneCore uses Alembic to version the shared platform schema. Application startup
does not silently create or alter tables. Apply reviewed migrations before starting
the API:

```powershell
cd onecore-ecosystem
python -m pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload
```

Create a new migration after changing SQLAlchemy models:

```powershell
alembic revision --autogenerate -m "describe schema change"
```

Review every generated migration before applying it. Test both upgrade and
downgrade against a disposable database. Back up production data before migration;
do not assume downgrade is safe after new application data has been written.

The initial revision `0001_initial` creates the existing shared platform tables:
users, organizations, memberships, branches, records, audit events, custom
domains, system notices, notice dismissals and organization invitations.

The Docker image applies `alembic upgrade head` before launching the API.
CI applies migrations against a clean SQLite database before running tests.
