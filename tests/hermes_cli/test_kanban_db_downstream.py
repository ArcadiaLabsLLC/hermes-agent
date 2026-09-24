"""Fork-owned tests moved out of ``tests/hermes_cli/test_kanban_db.py`` (seam Stage 5).

Same names, same bodies; the upstream file keeps only upstream's tests.
"""

from __future__ import annotations

from hermes_cli import kanban_crash_evidence as kb


def test_redact_secrets_strips_common_credentials():
    """Bearer/JWT/Authorization/cookies/signed-URL params must be redacted.

    Crash artifacts capture log tails verbatim; the redactor is the only
    thing standing between an OOM-killed worker's recent stdout and a
    leaked session token on disk.
    """
    bearer = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ.signature_123"
    api_key = "sk-live-abcdefghijklmnop"
    raw = (
        "GET /v1/x HTTP/1.1\n"
        f"Authorization: Bearer {bearer}\n"
        "Cookie: session=secret-value; csrf=12345\n"
        f"x-api-key: {api_key}\n"
        "GET /s3/obj?X-Amz-Signature=deadbeef&X-Amz-Credential=AKIAxxx "
        "&Expires=1700000000&Signature=abcd1234 HTTP/1.1\n"
        "payload {\"api_key\": \"ABCDEFGHIJKLMN\", \"token\": \"tok_live_xyz\"}\n"
    )
    out = kb._redact_secrets(raw)
    # Sensitive substrings must be gone.
    for forbidden in [
        bearer, "secret-value", api_key, "deadbeef", "AKIAxxx",
        "1700000000", "abcd1234", "ABCDEFGHIJKLMN", "tok_live_xyz",
    ]:
        assert forbidden not in out, (
            f"redaction leaked {forbidden!r} from input; got: {out!r}"
        )
    # Redaction marker should appear so operators see a redaction happened.
    assert "[REDACTED]" in out


def test_tail_bytes_returns_bounded_redacted_string(tmp_path):
    """``_tail_bytes_redacted`` should cap bytes and strip secrets."""
    p = tmp_path / "worker.log"
    # Construct ~4KB of innocuous text + a tail line with a Bearer token.
    secret = "abcdef1234567890SECRET"
    body = ("line of mostly-harmless log output\n" * 200).encode()
    body += f"Authorization: Bearer {secret}\n".encode()
    p.write_bytes(body)
    out = kb._tail_bytes_redacted(p, limit=512)
    assert out is not None
    assert len(out.encode("utf-8")) <= 700  # bounded; small slack for chars
    assert secret not in out
    assert "Authorization" in out  # surrounding context preserved
