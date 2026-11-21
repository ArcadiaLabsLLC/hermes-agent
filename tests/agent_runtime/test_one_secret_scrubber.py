"""One scrubber decides what is hidden (RT-ONE-SECRET-SCRUBBER-DECIDES-WHAT-IS-HIDDEN).

Upstream's ``agent.redact`` owns the credential shapes; ``agent_runtime.redaction``
adds only what upstream lacks. Three pins:

* every upstream secret shape -- each known key prefix and each structural family
  its own fixtures carry -- is hidden by the fork's tree walks, so a shape upstream
  learns reaches the fork's surfaces with no fork edit;
* every case the fork's own scrubber hid before it handed the decision to upstream
  is still hidden;
* each fork-only extension still catches something upstream alone leaves visible
  (when upstream learns it, the extension is a duplicate and goes).
"""

from __future__ import annotations

import json
import re

import pytest

import agent.redact as upstream
from agent_runtime.redaction import (
    is_secret_field_name,
    redact_transport_text,
    scrub_secret_value_tree,
    scrub_secret_values,
    scrub_tree,
)

_BODIES = (
    "Ab3dE5gH7jK9mN1pQ3sT5vX7zB9dF1hJ3kL5",
    "AB3DE5GH7JK9MN1P",
    "12345-Ab3dE5gH7jK9mN1pQ3sT5vX7z",
)


def _prefix_samples() -> list[str]:
    """One concrete key per upstream prefix pattern: its literal prefix and the first
    body that makes the whole pattern match."""

    samples = []
    for pattern in upstream._PREFIX_PATTERNS:
        # An unquantified class stands for its first character, ``\\d+`` for one digit,
        # ``\\.`` for a dot: ``xox[baprs]-`` gives ``xoxb-``, ``xapp-\\d+-`` ``xapp-1-``.
        spelled = re.sub(r"\[\\?(.)[^\]]*\](?![{*+?])", r"\1", pattern)
        spelled = spelled.replace("\\d+", "1").replace("\\.", ".")
        prefix = re.match(r"[A-Za-z0-9_.\-]*", spelled).group(0)
        sample = next(
            (prefix + body for body in _BODIES if re.fullmatch(pattern, prefix + body)), None
        )
        assert sample, f"no sample body fits upstream pattern {pattern!r}"
        samples.append(sample)
    return samples


#: Upstream's structural families, each as (text, the secret in it) — taken from
#: ``tests/agent/test_redact.py`` and ``test_redact_leak_shapes.py``.
_UPSTREAM_STRUCTURAL = [
    ("-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA7x\n-----END RSA PRIVATE KEY-----", "MIIEowIBAAKCAQEA7x"),
    ("AGE-SECRET-KEY-1QYQSZQGPQYQSZQGPQYQSZQGPQYQSZQGP", "QYQSZQGPQYQSZQGPQYQSZQGP"),
    ("postgres://app:s3cretpwq@db.example.com:5432/core", "s3cretpwq"),
    ("Host=db;Username=app;Password=s3cretpw;Database=x", "s3cretpw"),
    ("Authorization: Bearer q7Zr4Lm9Xc2Vb5Nw8Kd3", "q7Zr4Lm9Xc2Vb5Nw8Kd3"),
    ("OPENAI_API_KEY=q7Zr4Lm9Xc2Vb5Nw8Kd3Hf6J", "q7Zr4Lm9Xc2Vb5Nw8Kd3Hf6J"),
    ('{"api_key": "q7Zr4Lm9Xc2Vb5Nw8Kd3Hf6J"}', "q7Zr4Lm9Xc2Vb5Nw8Kd3Hf6J"),
    ("{'BRAVE_API_KEY': 'q7Zr4Lm9Xc2Vb5Nw8Kd3Hf6J'}", "q7Zr4Lm9Xc2Vb5Nw8Kd3Hf6J"),
    ('api_key: "q7Zr4Lm9Xc2Vb5Nw8Kd3Hf6J"', "q7Zr4Lm9Xc2Vb5Nw8Kd3Hf6J"),
    ("dbpassword: hunter2xyz", "hunter2xyz"),
    ("PGPASSWORD=s3cretpw psql -h db", "s3cretpw"),
    ("x-api-key: q7Zr4Lm9Xc2Vb5Nw8Kd3", "q7Zr4Lm9Xc2Vb5Nw8Kd3"),
    ("Cookie: session=q7Zr4Lm9Xc2Vb5Nw8Kd3", "q7Zr4Lm9Xc2Vb5Nw8Kd3"),
    ("mysql --password=s3cretpwq -u app", "s3cretpwq"),
    ("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0.SflKxwRJSMeKKF2QT4fwpM", "SflKxwRJSMeKKF2QT4fwpM"),
]


def _upstream_cases() -> list[tuple[str, str]]:
    return [(sample, sample) for sample in _prefix_samples()] + _UPSTREAM_STRUCTURAL


def _hidden(secret: str, out: object) -> bool:
    rendered = out if isinstance(out, str) else json.dumps(out)
    return secret not in rendered


def test_every_upstream_secret_is_hidden_by_the_forks_tree_walks():
    cases = _upstream_cases()
    assert len(cases) == len(upstream._PREFIX_PATTERNS) + len(_UPSTREAM_STRUCTURAL)
    leaked = []
    for text, secret in cases:
        tree = {"frame": {"rows": [{"label": "note", "detail": f"seen {text} here"}], "tail": (text,)}}
        walked = scrub_tree(tree, scrub=scrub_secret_values, list_cap=50)
        valued = scrub_secret_value_tree(tree)
        if not (_hidden(secret, walked) and _hidden(secret, valued)):
            leaked.append(text)
    # MUTATION: return text unchanged from agent_runtime.redaction._redact_upstream
    # and every prefix sample but the fork's own JWT/assignment reach leaks here.
    assert leaked == []


# ── every case the fork's scrubber hid before upstream decided ─────────────────

_FORK_TEXT_CASES = [
    ("sk-abcdefghijklmnop", "abcdefghijklmnop"),
    ("ghp_abcdefghij1234567890", "abcdefghij1234567890"),
    ("gho_abcdefghij1234567890", "abcdefghij1234567890"),
    ("ghu_abcdefghij1234567890", "abcdefghij1234567890"),
    ("ghs_abcdefghij1234567890", "abcdefghij1234567890"),
    ("ghr_abcdefghij1234567890", "abcdefghij1234567890"),
    ("github_pat_abcdefghij1234567890", "abcdefghij1234567890"),
    ("xoxa-abcdefghij", "abcdefghij"),
    ("xoxb-abcdefghij", "abcdefghij"),
    ("xoxp-abcdefghij", "abcdefghij"),
    ("xoxr-abcdefghij", "abcdefghij"),
    ("xoxs-abcdefghij", "abcdefghij"),
    ("AKIAABCDEFGHIJKLMNOP", "ABCDEFGHIJKLMNOP"),
    ("AIzaabcdefghijklmnopqrstuvwxyz0123", "abcdefghijklmnopqrstuvwxyz0123"),
    ("eyJabcdefgh.ijklmnop.qrstuvwx", "qrstuvwx"),
    ("call with Bearer abcdefghijkl1234 now", "abcdefghijkl1234"),
    ("authorization=abcdefghijkl1234", "abcdefghijkl1234"),
    ("proxy-authorization: abcdefghijkl1234", "abcdefghijkl1234"),
    ("x-api-key=abcdefghijkl1234", "abcdefghijkl1234"),
    ("api-key: abcdefghijkl1234", "abcdefghijkl1234"),
    ("cookie=abcdefghijkl1234", "abcdefghijkl1234"),
    ("set-cookie: abcdefghijkl1234", "abcdefghijkl1234"),
    ("https://alice:hunter2pw@example.com/x", "hunter2pw"),
    ("https://s3.example.com/o?X-Amz-Signature=abc123def", "abc123def"),
    ("https://s3.example.com/o?X-Amz-Credential=abc123def", "abc123def"),
    ("https://example.com/o?security-token=abc123def", "abc123def"),
    ("https://example.com/o?access_token=abc123def", "abc123def"),
    ("https://example.com/o?api_key=abc123def", "abc123def"),
    ("https://example.com/o?apikey=abc123def", "abc123def"),
    ("https://example.com/o?token=abc123def", "abc123def"),
    ("https://example.com/o?sig=abc123def", "abc123def"),
    ("https://example.com/o?key=abc123def", "abc123def"),
    ("my password=hunter2", "hunter2"),
    ("api_key: abc123def", "abc123def"),
    ("access_token=abc123def", "abc123def"),
    ("refresh_token: abc123def", "abc123def"),
    ("id_token: abc123def", "abc123def"),
    ("bearer=abc123def", "abc123def"),
    ("credential: abc123def", "abc123def"),
    ("passwd=abc123def", "abc123def"),
    ("private_key: abc123def", "abc123def"),
    ("secret=abc123def", "abc123def"),
    ('{"token": "abc123def"}', "abc123def"),
]


@pytest.mark.parametrize(("text", "secret"), _FORK_TEXT_CASES)
def test_a_case_the_forks_scrubber_hid_is_still_hidden(text, secret):
    # MUTATION: drop BEARER_TOKEN_RE from _fork_transport_passes and the bare
    # Bearer case reddens; drop _SHORT_JWT_RE and the eyJ case reddens.
    assert _hidden(secret, scrub_secret_values(text))
    assert _hidden(secret, scrub_secret_value_tree({"detail": text}))


def test_transport_text_hides_an_exact_secret_and_every_upstream_shape():
    out = redact_transport_text("pw=zzexactzz key hf_Ab3dE5gH7jK9mN1pQ3sT", secrets=("zzexactzz",))
    assert "zzexactzz" not in out and "Ab3dE5gH7jK9mN1pQ3sT" not in out


@pytest.mark.parametrize(
    "key",
    [
        "token", "secret", "password", "passwd", "passphrase", "authorization", "cookie",
        "credential", "credentials", "api_key", "apikey", "private_key", "access_key", "secret_key",
        "accessToken", "client-secret", "db.password", "sshPassphrase", "proxy_authorization",
        "sessionCookie", "pass\nword", "x-api-key",
    ],
)
def test_a_field_the_fork_named_secret_is_still_secret(key):
    # MUTATION: drop "cookie" from FORK_ONLY_SECRET_FIELD_TAILS and cookie /
    # sessionCookie redden.
    assert is_secret_field_name(key)
    assert scrub_secret_value_tree({key: "abc123def"}) == {key: "[REDACTED]"}


@pytest.mark.parametrize("key", ["credential_profile", "token_count", "password_policy", "public_key", "key_id"])
def test_a_field_that_names_no_secret_stays_shown(key):
    assert not is_secret_field_name(key)


# ── each fork-only extension still covers a gap ───────────────────────────────

_FORK_ONLY_TEXT = [
    ("call with Bearer abcdefghijkl1234 now", "abcdefghijkl1234"),
    ("authorization=abcdefghijkl1234", "abcdefghijkl1234"),
    ("https://s3.example.com/o?X-Amz-Signature=abc123def", "abc123def"),
    ("my password=hunter2", "hunter2"),
    ("eyJabcdefgh.ijklmnop.qrstuvwx", "qrstuvwx"),
]


@pytest.mark.parametrize(("text", "secret"), _FORK_ONLY_TEXT)
def test_a_fork_only_pass_covers_what_upstream_alone_shows(text, secret):
    """When this reddens upstream learned the case: delete the fork's pass for it."""

    assert secret in upstream.redact_sensitive_text(text, force=True)
    assert _hidden(secret, scrub_secret_values(text))


@pytest.mark.parametrize("key", ["passphrase", "proxy_authorization", "session_cookie"])
def test_a_fork_only_field_tail_covers_what_upstream_alone_misses(key):
    assert not upstream.is_secret_field_name(key)
    assert is_secret_field_name(key)
