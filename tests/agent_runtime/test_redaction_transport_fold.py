"""The transport rules folded into ``agent_runtime.redaction`` from ``mobile_core``.

Embedded-hermes plan D0 item 2: before the July mobile core's ``redact.py`` is
re-homed, every rule it had that this module lacked lives here. Each case pairs
the credential with a clean control that must survive untouched.
"""

from __future__ import annotations

import pytest

from agent_runtime.redaction import (
    REDACTED_VALUE,
    TEXT_SECRET_VALUE_ASSIGNMENT_RE,
    is_credential_key,
    redact_transport_text,
    redact_transport_tree,
    redact_url,
)


def test_space_separated_bearer_token_is_masked_and_the_assignment_rules_miss_it():
    text = "upstream said: Bearer abc.DEF-123_xyz rejected"
    assert TEXT_SECRET_VALUE_ASSIGNMENT_RE.search(text) is None  # the gap this fold closes
    assert redact_transport_text(text) == f"upstream said: Bearer {REDACTED_VALUE} rejected"
    # Control: the scheme word with no token after it survives. (Like the TEXT
    # vocabulary, the rule over-matches prose such as "bearer of" on purpose —
    # redaction is display-only.)
    assert redact_transport_text("header missing Bearer") == "header missing Bearer"


@pytest.mark.parametrize("header", ["Cookie", "Set-Cookie", "X-Api-Key", "Proxy-Authorization"])
def test_credential_headers_are_masked(header):
    assert redact_transport_text(f"{header}: s3cr3tvalue; next") == f"{header}: {REDACTED_VALUE}; next"


def test_signed_url_query_values_are_masked_and_userinfo_dropped():
    url = "https://user:pw@bucket.example:8443/o?X-Amz-Signature=abc&key=k1&page=2"
    out = redact_url(url)
    assert "pw" not in out and "abc" not in out and "k1" not in out
    assert out.startswith("https://bucket.example:8443/o?")
    assert "page=2" in out  # control: an unsigned parameter survives


def test_urls_inside_text_are_redacted_and_non_urls_untouched():
    assert "sig=zz" not in redact_transport_text("GET https://h.example/p?sig=zz failed")
    assert redact_url("not a url") == "not a url"


def test_exact_secrets_are_masked():
    assert redact_transport_text("value opaque-42 leaked", secrets=("opaque-42", "")) == (
        f"value {REDACTED_VALUE} leaked"
    )


def test_tree_masks_credential_keys_and_walks_everything_else():
    tree = {
        "api_key": "plain",
        "Access_Token": "plain",
        "headers": {"Set-Cookie": "c=1"},
        "items": ("Bearer tok", 3, None, True),
        "name": "plain",
    }
    assert redact_transport_tree(tree) == {
        "api_key": REDACTED_VALUE,
        "Access_Token": REDACTED_VALUE,
        "headers": {"Set-Cookie": REDACTED_VALUE},
        "items": [f"Bearer {REDACTED_VALUE}", 3, None, True],
        "name": "plain",
    }


def test_credential_key_folds_underscore_and_case():
    assert is_credential_key(" X_API_KEY ")
    assert not is_credential_key("api_keys_count")
