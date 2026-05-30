"""Tests for agent_review.redaction."""

import pytest

from agent_review.redaction import redact

# ---------------------------------------------------------------------------
# AWS access key
# ---------------------------------------------------------------------------

class TestAwsAccessKey:
    def test_plain_text(self):
        text = "Use access key AKIAIOSFODNN7EXAMPLE for the S3 bucket."
        result = redact(text)
        assert "AKIAIOSFODNN7EXAMPLE" not in result
        assert "«REDACTED:aws-access-key»" in result

    def test_surrounding_text_preserved(self):
        text = "key=AKIAIOSFODNN7EXAMPLE and more text"
        result = redact(text)
        assert result.startswith("key=")
        assert "and more text" in result

    def test_multiple_keys(self):
        text = "AKIAIOSFODNN7EXAMPLE and AKIAI0SFODNN7EXAMPL"
        result = redact(text)
        # second one is only 19 chars after AKIA, not 16 uppercase alnum — should not match
        assert result.count("«REDACTED:aws-access-key»") >= 1


class TestAwsSecretKey:
    def test_assignment(self):
        text = "aws_secret_access_key = wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
        result = redact(text)
        assert "wJalrXUtnFEMI" not in result
        assert "«REDACTED:aws-secret-key»" in result
        assert "aws_secret_access_key" in result

    def test_secret_key_colon(self):
        # 40-char value (exactly AWS secret key length)
        text = "secret_key: abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMN"
        result = redact(text)
        assert "abcdefghijklmno" not in result
        assert "«REDACTED:aws-secret-key»" in result


# ---------------------------------------------------------------------------
# Generic password / secret assignments
# ---------------------------------------------------------------------------

class TestGenericAssignment:
    def test_password_double_quotes(self):
        text = 'password = "hunter2"'
        result = redact(text)
        assert "hunter2" not in result
        assert "«REDACTED:password»" in result
        assert "password" in result  # key is preserved

    def test_password_colon_no_quotes(self):
        text = "PASSWORD: hunter2"
        result = redact(text)
        assert "hunter2" not in result
        assert "«REDACTED:password»" in result

    def test_token_assignment(self):
        text = "token=supersecretvalue123"
        result = redact(text)
        assert "supersecretvalue123" not in result

    def test_api_key_assignment(self):
        text = "api_key = myverysecretapikey"
        result = redact(text)
        assert "myverysecretapikey" not in result

    def test_bearer_assignment(self):
        text = "bearer: eyJhbGciOiJSUzI1NiJ9.payload"
        result = redact(text)
        assert "eyJhbGciOiJSUzI1NiJ9" not in result

    def test_single_quoted_value(self):
        text = "secret='topsecret'"
        result = redact(text)
        assert "topsecret" not in result
        assert "«REDACTED:password»" in result


# ---------------------------------------------------------------------------
# Anthropic / OpenAI API keys
# ---------------------------------------------------------------------------

class TestApiKeys:
    def test_anthropic_key(self):
        text = "export ANTHROPIC_API_KEY=sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789"
        result = redact(text)
        # The sk-ant-... value is caught by the specific Anthropic pattern first.
        assert "sk-ant-api03" not in result
        # Some redaction marker must be present (either anthropic-api-key or password).
        assert "«REDACTED:" in result

    def test_openai_key(self):
        text = "OPENAI_KEY=sk-abcdefghijklmnopqrstuvwxyz"
        result = redact(text)
        assert "sk-abcdefghijklmnopqrstu" not in result
        assert "«REDACTED" in result

    def test_short_sk_not_redacted(self):
        # sk- with fewer than 20 chars after should NOT match
        text = "version: sk-1234"
        result = redact(text)
        assert result == text


# ---------------------------------------------------------------------------
# GitHub tokens
# ---------------------------------------------------------------------------

class TestGithubTokens:
    def test_fine_grained_token(self):
        # ghp_ + 36 alphanumeric chars = real GitHub fine-grained token format
        text = "GITHUB_TOKEN=ghp_abcdefghijklmnopqrstuvwxyzABCDEFGHIJKL"
        result = redact(text)
        assert "ghp_abcdefghijklmno" not in result
        assert "«REDACTED:github-token»" in result

    def test_oauth_token(self):
        text = "token: gho_1234567890abcdefghijklmnopqrstuvwxyz"
        result = redact(text)
        assert "gho_1234567890" not in result

    def test_server_token(self):
        text = "ghs_zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz"
        result = redact(text)
        assert "ghs_" not in result

    def test_40hex_with_github_context(self):
        # GITHUB_TOKEN=<40-hex> should be caught by the context-gated 40-hex pattern
        text = "GITHUB_TOKEN=a3f1b2c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0"
        result = redact(text)
        assert "a3f1b2c4d5e6f7a8b9c0" not in result
        # May be labeled github-token or password depending on which pass fires;
        # either way the raw hex is gone.
        assert "«REDACTED:" in result

    def test_40hex_git_sha_no_context_not_redacted(self):
        # A bare 40-hex string with no secret context must NOT be redacted
        text = "commit a3f1b2c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0 merged"
        result = redact(text)
        assert "a3f1b2c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0" in result

    def test_git_sha_unchanged(self):
        text = "Author: mj <test@example.com>\ncommit deadbeefcafebabe0123456789abcdef01234567"
        result = redact(text)
        assert "deadbeefcafebabe0123456789abcdef01234567" in result


# ---------------------------------------------------------------------------
# Slack tokens
# ---------------------------------------------------------------------------

class TestSlackTokens:
    def test_bot_token(self):
        text = "SLACK_TOKEN=xoxb-1234567890-abcdefghij"
        result = redact(text)
        assert "xoxb-1234567890" not in result
        assert "«REDACTED:slack-token»" in result

    def test_app_token(self):
        text = "token = xoxa-abcdefghij-klmnopqrst"
        result = redact(text)
        assert "xoxa-abcdefghij" not in result


# ---------------------------------------------------------------------------
# Google API keys
# ---------------------------------------------------------------------------

class TestGoogleApiKeys:
    def test_google_key(self):
        # Google API keys: "AIza" + exactly 35 base64url chars = 39 chars total
        text = "key=AIzaSyD-1234567890abcdefghijklmnopqrstu"
        result = redact(text)
        assert "AIzaSyD-1234567890" not in result
        assert "«REDACTED:google-api-key»" in result


# ---------------------------------------------------------------------------
# Bearer tokens
# ---------------------------------------------------------------------------

class TestBearerTokens:
    def test_authorization_header(self):
        text = "Authorization: Bearer eyJhbGciOiJSUzI1NiIsImtpZCI6ImtleS0xIn0.payload"
        result = redact(text)
        assert "eyJhbGciOiJSUzI1NiIsImtpZCI6ImtleS0xIn0" not in result
        assert "«REDACTED:bearer-token»" in result
        assert "Authorization: Bearer" in result

    def test_case_insensitive(self):
        text = "authorization: bearer mysecrettoken123456"
        result = redact(text)
        assert "mysecrettoken123456" not in result


# ---------------------------------------------------------------------------
# .pgpass lines
# ---------------------------------------------------------------------------

class TestPgpass:
    def test_pgpass_line(self):
        text = "198.51.100.22:5432:exampledb:exampleuser:supersecretdbpassword"
        result = redact(text)
        assert "supersecretdbpassword" not in result
        assert "«REDACTED:password»" in result
        # The first four fields should be preserved
        assert "198.51.100.22:5432:exampledb:exampleuser:" in result

    def test_pgpass_wildcard_host(self):
        text = "*:5432:*:postgres:anotherpassword"
        result = redact(text)
        assert "anotherpassword" not in result

    def test_pgpass_in_multiline(self):
        text = "# comment\n192.168.1.1:5432:mydb:user:mypassword\n# end"
        result = redact(text)
        assert "mypassword" not in result
        assert "# comment" in result
        assert "# end" in result


# ---------------------------------------------------------------------------
# PEM private key blocks
# ---------------------------------------------------------------------------

class TestPrivateKey:
    PEM = (
        "-----BEGIN RSA PRIVATE KEY-----\n"
        "MIIEpAIBAAKCAQEA0Z3VS5JJcds3xHn/ygWep4PAtcsF7NHbTXBHABk7rDGAJU65\n"
        "-----END RSA PRIVATE KEY-----"
    )

    def test_pem_block_replaced(self):
        result = redact(self.PEM)
        assert "MIIEpAIBAAKCAQEA" not in result
        assert "«REDACTED:private-key»" in result
        assert "BEGIN" not in result

    def test_pem_block_in_larger_text(self):
        text = f"SSH config:\n{self.PEM}\nEnd of config."
        result = redact(text)
        assert "MIIEpAIBAAKCAQEA" not in result
        assert "SSH config:" in result
        assert "End of config." in result

    def test_ec_private_key(self):
        pem = (
            "-----BEGIN EC PRIVATE KEY-----\n"
            "MHQCAQEEIOaE9zs5jIoJKFrNFo1oBLsv0BkP\n"
            "-----END EC PRIVATE KEY-----"
        )
        result = redact(pem)
        assert "«REDACTED:private-key»" in result


# ---------------------------------------------------------------------------
# False positive guards
# ---------------------------------------------------------------------------

class TestFalsePositives:
    def test_git_sha_not_redacted(self):
        # 40-hex without any secret-signalling context
        text = "Merge commit a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0"
        result = redact(text)
        assert "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0" in result

    def test_version_string_not_redacted(self):
        text = "Running Python 3.12.0"
        result = redact(text)
        assert result == text

    def test_uuid_not_redacted(self):
        text = "id: 550e8400-e29b-41d4-a716-446655440000"
        result = redact(text)
        assert "550e8400-e29b-41d4-a716-446655440000" in result

    def test_empty_string(self):
        assert redact("") == ""

    def test_no_secrets(self):
        text = "Hello, world! This is a normal log message with no secrets."
        assert redact(text) == text

    def test_normal_url_not_redacted(self):
        text = "See https://docs.anthropic.com/en/api for details."
        result = redact(text)
        assert "https://docs.anthropic.com" in result


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------

class TestIdempotency:
    @pytest.mark.parametrize("text", [
        "password = hunter2",
        "AKIAIOSFODNN7EXAMPLE",
        "sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789",
        "xoxb-1234567890-abcdefghij",
        "198.51.100.22:5432:mydb:exampleuser:s3cret",
        "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload",
        (
            "-----BEGIN RSA PRIVATE KEY-----\n"
            "MIIEpAIBAAKCAQEA0Z3VS5JJcds3xHn\n"
            "-----END RSA PRIVATE KEY-----"
        ),
        "Hello, no secrets here.",
        "",
    ])
    def test_idempotent(self, text: str):
        once = redact(text)
        twice = redact(once)
        assert once == twice, f"Not idempotent:\n  once={once!r}\n  twice={twice!r}"
