import json
from pathlib import Path

from scripts import postgres_backup


def test_backup_verify_checks_manifest_checksum_and_archive_listing(tmp_path, monkeypatch):
    archive=tmp_path/"backup.dump"
    archive.write_bytes(b"verified-postgresql-archive")
    manifest={
        "format":"onecore-postgresql-custom-v1",
        "database":"onecore",
        "file":archive.name,
        "size_bytes":archive.stat().st_size,
        "sha256":postgres_backup.sha256(archive),
        "verified_archive_listing":True,
    }
    archive.with_suffix(archive.suffix+".manifest.json").write_text(json.dumps(manifest),encoding="utf-8")
    calls=[]
    def fake_run(command,**kwargs):
        calls.append(command)
        return type("Result",(),{"returncode":0,"stdout":"archive contents","stderr":""})()
    monkeypatch.setattr(postgres_backup.subprocess,"run",fake_run)
    postgres_backup.verify(type("Args",(),{"archive":str(archive)})())
    assert calls and calls[0][:2]==["pg_restore","--list"]


def test_backup_verify_rejects_modified_archive(tmp_path, monkeypatch):
    archive=tmp_path/"backup.dump"
    archive.write_bytes(b"original")
    manifest={"size_bytes":8,"sha256":"0"*64}
    archive.with_suffix(archive.suffix+".manifest.json").write_text(json.dumps(manifest),encoding="utf-8")
    monkeypatch.setattr(postgres_backup.subprocess,"run",lambda *a,**k:None)
    try:
        postgres_backup.verify(type("Args",(),{"archive":str(archive)})())
    except SystemExit as exc:
        assert "integrity check failed" in str(exc)
    else:
        raise AssertionError("modified archive was accepted")


def test_connection_args_requires_postgresql_and_uses_password_environment():
    args,env,database=postgres_backup.connection_args("postgresql://operator:secret@db.example.test:5432/onecore?sslmode=require")
    assert database=="onecore"
    assert env["PGPASSWORD"]=="secret"
    assert env["PGSSLMODE"]=="require"
    assert "secret" not in " ".join(args)
