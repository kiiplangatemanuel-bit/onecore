#!/usr/bin/env python3
"""Create and verify PostgreSQL custom-format backups; restore only to an explicit empty target.

Credentials are read from environment URLs and passed to libpq via PGPASSWORD,
not embedded in command-line arguments. The script never deletes the target database.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy.engine import make_url


def connection_args(raw_url):
    if not raw_url:
        raise SystemExit("A database URL environment variable is required")
    url = make_url(raw_url)
    if url.get_backend_name() != "postgresql":
        raise SystemExit("Backup/restore requires PostgreSQL")
    env = os.environ.copy()
    if url.password is not None:
        env["PGPASSWORD"] = url.password
    args = ["--host", url.host or "localhost", "--port", str(url.port or 5432),
            "--username", url.username or "", "--dbname", url.database or "postgres"]
    query = dict(url.query)
    if query.get("sslmode"):
        env["PGSSLMODE"] = query["sslmode"]
    return args, env, url.database or "postgres"


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(command, env):
    subprocess.run(command, env=env, check=True)


def backup(args):
    conn, env, database = connection_args(os.getenv("ONECORE_BACKUP_DATABASE_URL") or os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL"))
    target = Path(args.output).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise SystemExit(f"Refusing to overwrite existing backup: {target}")
    manifest_path = target.with_suffix(target.suffix + ".manifest.json")
    temporary_manifest = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
    try:
        run(["pg_dump", *conn, "--format=custom", "--no-owner", "--no-acl", "--file", str(target)], env)
        run(["pg_restore", "--list", str(target)], env)
        digest = sha256(target)
        manifest = {"format":"onecore-postgresql-custom-v1","database":database,
                    "created_at":datetime.now(timezone.utc).isoformat(),
                    "file":target.name,"size_bytes":target.stat().st_size,"sha256":digest,
                    "verified_archive_listing":True}
        temporary_manifest.write_text(json.dumps(manifest, indent=2)+"\n", encoding="utf-8")
        temporary_manifest.replace(manifest_path)
    except Exception:
        target.unlink(missing_ok=True)
        manifest_path.unlink(missing_ok=True)
        temporary_manifest.unlink(missing_ok=True)
        raise
    print(json.dumps(manifest, indent=2))


def verify(args):
    target = Path(args.archive).resolve()
    manifest_path = target.with_suffix(target.suffix + ".manifest.json")
    if not target.is_file() or not manifest_path.is_file():
        raise SystemExit("Backup archive or checksum manifest is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("format") != "onecore-postgresql-custom-v1":
        raise SystemExit("Unsupported or invalid backup manifest format")
    actual = sha256(target)
    if actual != manifest.get("sha256") or target.stat().st_size != manifest.get("size_bytes"):
        raise SystemExit("Backup integrity check failed: checksum or size mismatch")
    subprocess.run(["pg_restore", "--list", str(target)], check=True, capture_output=True, text=True)
    print(json.dumps({"verified":True,"archive":str(target),"sha256":actual,"size_bytes":target.stat().st_size}))


def restore(args):
    if not args.allow_restore:
        raise SystemExit("Restore is gated. Pass --allow-restore after reviewing the target and runbook.")
    target_url = os.getenv("ONECORE_RESTORE_DATABASE_URL", "")
    conn, env, database = connection_args(target_url)
    if args.confirm_target != database:
        raise SystemExit("--confirm-target must exactly match the database name in ONECORE_RESTORE_DATABASE_URL")
    archive = Path(args.archive).resolve()
    verify(argparse.Namespace(archive=str(archive)))
    # Deliberately do not use --clean/--if-exists. Check the destination first
    # and only restore into an empty, isolated database.
    probe = subprocess.run(["psql", *conn, "--tuples-only", "--no-align", "--command",
        "SELECT (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname NOT IN ('pg_catalog','information_schema','pg_toast') AND c.relkind IN ('r','p','v','m','S','f')) + (SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname NOT IN ('pg_catalog','information_schema','pg_toast')) + (SELECT count(*) FROM pg_namespace WHERE nspname NOT IN ('pg_catalog','information_schema','pg_toast','public'))"],
        env=env, check=True, capture_output=True, text=True)
    if int(probe.stdout.strip() or "0") != 0:
        raise SystemExit("Restore target is not empty; refusing to overwrite existing data")
    run(["pg_restore", "--exit-on-error", "--no-owner", "--no-acl", "--dbname", database,
         "--host", conn[1], "--port", conn[3], "--username", conn[5], str(archive)], env)
    print(json.dumps({"restored":True,"target_database":database,
                      "warning":"Run post-restore validation and keep the target isolated until approved."}))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest="command",required=True)
    b=commands.add_parser("backup");b.add_argument("--output",required=True);b.set_defaults(func=backup)
    v=commands.add_parser("verify");v.add_argument("--archive",required=True);v.set_defaults(func=verify)
    r=commands.add_parser("restore");r.add_argument("--archive",required=True);r.add_argument("--confirm-target",required=True);r.add_argument("--allow-restore",action="store_true");r.set_defaults(func=restore)
    args=parser.parse_args()
    try: args.func(args)
    except subprocess.CalledProcessError as exc:
        print(f"Command failed with exit code {exc.returncode}",file=sys.stderr);raise SystemExit(exc.returncode)


if __name__=="__main__":
    main()
