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
    manifest={"format":"onecore-postgresql-custom-v1","size_bytes":8,"sha256":"0"*64}
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



def test_restore_refuses_database_with_existing_objects(tmp_path, monkeypatch):
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
    monkeypatch.setenv("ONECORE_RESTORE_DATABASE_URL","postgresql://restore:secret@db.example.test:5432/recovery?sslmode=require")
    calls=[]
    def fake_run(command,**kwargs):
        calls.append(command)
        return type("Result",(),{"returncode":0,"stdout":"1","stderr":""})()
    monkeypatch.setattr(postgres_backup.subprocess,"run",fake_run)
    args=type("Args",(),{"allow_restore":True,"confirm_target":"recovery","archive":str(archive)})()
    try:
        postgres_backup.restore(args)
    except SystemExit as exc:
        assert "not empty" in str(exc)
    else:
        raise AssertionError("restore accepted a database with existing objects")
    assert any(command[0]=="psql" for command in calls)
    assert not any(command[0]=="pg_restore" and "--exit-on-error" in command for command in calls)



def test_restore_verifies_archive_empty_target_and_core_schema(tmp_path, monkeypatch, capsys):
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
    monkeypatch.setenv("ONECORE_RESTORE_DATABASE_URL","postgresql://restore:secret@db.example.test:5432/recovery?sslmode=require")
    calls=[]
    def fake_run(command,**kwargs):
        calls.append(command)
        stdout="0" if command[0]=="psql" and "SELECT (SELECT count(*)" in command[-1] else "ok"
        return type("Result",(),{"returncode":0,"stdout":stdout,"stderr":""})()
    monkeypatch.setattr(postgres_backup.subprocess,"run",fake_run)
    args=type("Args",(),{"allow_restore":True,"confirm_target":"recovery","archive":str(archive)})()
    postgres_backup.restore(args)
    output=json.loads(capsys.readouterr().out)
    assert output["restored"] is True and output["smoke_test"]=="passed"
    restore_commands=[command for command in calls if command[0]=="pg_restore" and "--exit-on-error" in command]
    assert len(restore_commands)==1 and "--no-acl" in restore_commands[0]
    assert any(command[0]=="psql" and "to_regclass" in command[-1] for command in calls)
