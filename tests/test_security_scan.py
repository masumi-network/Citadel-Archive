from __future__ import annotations

import json

from kb.security_scan import (
    SecurityScanEntry,
    redact_secrets,
    scan_text_entries,
)

GITHUB_TOKEN = "ghp_abcdefghijklmnopqrstuvwxyz0123456789"
FINE_GRAINED_TOKEN = "github_pat_" + "a1B2" * 12
AWS_KEY = "AKIAIOSFODNN7EXAMPLE"
SLACK_TOKEN = "-".join(["xoxb", "1234567890", "abcdefghijklmnop"])
STRIPE_KEY = "sk_live_abcdefghijklmnop1234"
PRIVATE_KEY = "-----BEGIN RSA PRIVATE KEY-----"
GENERIC_ASSIGNMENT = 'password = "hunter2-super-secret"'


def entry(text: str, *, location: str = "masumi-network/agent") -> SecurityScanEntry:
    return SecurityScanEntry(source="commit", location=location, text=text)


def scan(text: str) -> dict[str, object]:
    return scan_text_entries([entry(text)])


def categories(result: dict[str, object]) -> set[str]:
    return {finding["category"] for finding in result["findings"]}  # type: ignore[index]


def test_github_token_pattern_blocks_at_critical() -> None:
    result = scan(f"deploy with {GITHUB_TOKEN} now")

    assert result["blocked"] is True
    assert result["highest_severity"] == "critical"
    assert "github_token" in categories(result)


def test_citadel_access_token_is_blocked() -> None:
    token = "ctdl_" + "aB3" * 12
    result = scan(f"paste {token} here")

    assert result["blocked"] is True
    assert "citadel_access_token" in categories(result)


def test_database_connection_url_is_blocked() -> None:
    url = "postgresql://user:secret@db.example.com:5432/app"
    result = scan(f"DATABASE_URL={url}")

    assert result["blocked"] is True
    assert "database_connection_url" in categories(result)


def test_fine_grained_github_token_is_detected() -> None:
    assert "github_fine_grained_token" in categories(scan(f"use {FINE_GRAINED_TOKEN}"))


def test_aws_access_key_is_detected() -> None:
    assert "aws_access_key" in categories(scan(f"creds {AWS_KEY} leaked"))


def test_slack_token_is_detected() -> None:
    assert "slack_token" in categories(scan(f"bot uses {SLACK_TOKEN}"))


def test_stripe_live_secret_is_detected() -> None:
    assert "stripe_live_secret" in categories(scan(f"billing key {STRIPE_KEY}"))


def test_private_key_marker_is_detected() -> None:
    assert "private_key_marker" in categories(scan(f"{PRIVATE_KEY}\nMIIE..."))


def test_generic_secret_assignment_is_detected_at_high() -> None:
    result = scan(GENERIC_ASSIGNMENT)

    assert result["blocked"] is True
    assert "secret_assignment" in categories(result)


def test_findings_never_contain_the_raw_secret() -> None:
    for secret in (GITHUB_TOKEN, AWS_KEY, SLACK_TOKEN, STRIPE_KEY):
        serialized = json.dumps(scan(f"commit message includes {secret}"))
        assert secret not in serialized
        assert "[REDACTED]" not in serialized  # findings carry pattern evidence, not values


def test_duplicate_findings_are_deduped_by_fingerprint() -> None:
    duplicated = [entry(f"leak {AWS_KEY}"), entry(f"leak {AWS_KEY}")]

    result = scan_text_entries(duplicated)

    assert result["finding_count"] == 1


def test_distinct_locations_produce_distinct_fingerprints() -> None:
    entries = [
        entry(f"leak {AWS_KEY}", location="masumi-network/agent"),
        entry(f"leak {AWS_KEY}", location="masumi-network/registry"),
    ]

    result = scan_text_entries(entries)

    assert result["finding_count"] == 2
    fingerprints = {finding["fingerprint"] for finding in result["findings"]}  # type: ignore[index]
    assert len(fingerprints) == 2


def test_benign_text_produces_no_findings() -> None:
    benign = (
        "Bumped version to 1.2.3, refreshed the README, and linked "
        "https://github.com/masumi-network/agent for context. Tokens of appreciation all around."
    )

    result = scan(benign)

    assert result["ok"] is True
    assert result["blocked"] is False
    assert result["finding_count"] == 0


def test_medium_findings_do_not_block_at_high_threshold() -> None:
    result = scan_text_entries(
        [entry("see https://bit.ly/3xyzabc for details")],
        block_severity="high",
    )

    assert result["blocked"] is False
    assert "url_shortener" in categories(result)


def test_redact_secrets_masks_known_and_pattern_matched_values() -> None:
    message = (
        f"Authorization: Bearer ctdl_abc123token bearer {GITHUB_TOKEN} "
        f'api_key=sk-test password: "p4ssw0rd-value"'
    )

    redacted = redact_secrets(message, "explicit-known-secret")

    assert "ctdl_abc123token" not in redacted
    assert GITHUB_TOKEN not in redacted
    assert "sk-test" not in redacted
    assert "p4ssw0rd-value" not in redacted
    assert "[REDACTED]" in redacted


def test_redact_secrets_replaces_explicitly_known_secrets() -> None:
    assert redact_secrets("body with explicit-value", "explicit-value") == "body with [REDACTED]"


def test_redact_secrets_keeps_benign_text_intact() -> None:
    benign = "GitHub sync finished for masumi-network: 12 repos scanned"

    assert redact_secrets(benign) == benign
