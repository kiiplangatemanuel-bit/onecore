"""Fail-closed ClamAV INSTREAM integration for quarantined Support objects."""
import hashlib
import socket
import struct

from fastapi import HTTPException

from app.core.config import settings


def parse_clamav_response(response: bytes) -> bool:
    """Return True for FOUND, False for OK; reject every other response."""
    normalized = response.strip().rstrip(b"\\x00").decode("utf-8", errors="replace")
    if normalized.endswith(": OK"):
        return False
    if " FOUND" in normalized:
        return True
    raise ValueError("ClamAV returned an invalid or error response")


def scan_s3_attachment(storage, attachment) -> dict:
    if not settings.clamav_host:
        raise HTTPException(503, "Malware scanner is not configured; attachment remains quarantined")
    try:
        remote = storage.get_object(Bucket=settings.s3_bucket, Key=attachment.object_key)
        body = remote["Body"]
        digest = hashlib.sha256()
        total = 0
        with socket.create_connection(
            (settings.clamav_host, settings.clamav_port),
            timeout=settings.clamav_timeout_seconds,
        ) as scanner:
            scanner.settimeout(settings.clamav_timeout_seconds)
            scanner.sendall(b"zINSTREAM\\0")
            while True:
                chunk = body.read(64 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > attachment.size_bytes or total > 10 * 1024 * 1024:
                    raise ValueError("Stored attachment exceeds its declared size")
                digest.update(chunk)
                scanner.sendall(struct.pack("!I", len(chunk)) + chunk)
            if total != attachment.size_bytes:
                raise ValueError("Stored attachment size does not match metadata")
            scanner.sendall(struct.pack("!I", 0))
            response = bytearray()
            while len(response) < 4096:
                part = scanner.recv(1024)
                if not part:
                    break
                response.extend(part)
                if b"\\0" in part or b"\\n" in part:
                    break
        infected = parse_clamav_response(bytes(response))
        return {
            "infected": infected,
            "result": "infected" if infected else "clean",
            "sha256": digest.hexdigest(),
            "bytes_scanned": total,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(503, "Malware scan failed; attachment remains quarantined") from exc
    finally:
        try:
            body.close()
        except (UnboundLocalError, Exception):
            pass
