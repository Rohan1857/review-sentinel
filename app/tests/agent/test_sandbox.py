# type: ignore
import os
from unittest.mock import patch

from review_sentinel.agent.sandbox import (
    REDACTED,
    SAFE_ENV_VARS,
    build_sanitized_env,
    sanitize_output,
)


class TestBuildSanitizedEnv:
    def test_keeps_safe_vars(self):
        env = {"PATH": "/usr/bin", "HOME": "/home/user", "GITLAB_TOKEN": "secret"}

        with patch.dict(os.environ, env, clear=True):
            result = build_sanitized_env()

        assert result["PATH"] == "/usr/bin"
        assert result["HOME"] == "/home/user"
        assert "GITLAB_TOKEN" not in result

    def test_strips_secrets(self):
        env = {
            "PATH": "/usr/bin",
            "GITLAB_TOKEN": "glpat-xxxx",
            "REDIS_URL": "redis://localhost:6379",
            "ANTHROPIC_API_KEY": "sk-ant-xxx",
            "ENCRYPTION_KEY": "fernet-key",
            "ADMIN_API_TOKEN": "admin-secret",
        }

        with patch.dict(os.environ, env, clear=True):
            result = build_sanitized_env()

        assert "GITLAB_TOKEN" not in result
        assert "REDIS_URL" not in result
        assert "ANTHROPIC_API_KEY" not in result
        assert "ENCRYPTION_KEY" not in result
        assert "ADMIN_API_TOKEN" not in result

    def test_extra_safe_vars(self):
        env = {"PATH": "/usr/bin", "MY_CUSTOM": "value"}

        with patch.dict(os.environ, env, clear=True):
            result = build_sanitized_env(extra_safe_vars=["MY_CUSTOM"])

        assert result["MY_CUSTOM"] == "value"

    def test_empty_env(self):
        with patch.dict(os.environ, {}, clear=True):
            result = build_sanitized_env()

        assert result == {}

    def test_all_safe_vars_preserved(self):
        env = {var: f"value_{var}" for var in SAFE_ENV_VARS}

        with patch.dict(os.environ, env, clear=True):
            result = build_sanitized_env()

        for var in SAFE_ENV_VARS:
            assert result[var] == f"value_{var}"


class TestSanitizeOutput:
    def test_redacts_gitlab_pat(self):
        token = "glpat-" + "A" * 25
        result = sanitize_output(f"Token: {token}")

        assert "glpat-" not in result
        assert REDACTED in result

    def test_redacts_github_pat(self):
        token = "ghp_" + "A" * 36
        result = sanitize_output(f"Token: {token}")

        assert "ghp_" not in result
        assert REDACTED in result

    def test_redacts_github_app_token(self):
        token = "ghs_" + "A" * 36
        result = sanitize_output(f"Token: {token}")

        assert "ghs_" not in result
        assert REDACTED in result

    def test_redacts_openai_key(self):
        token = "sk-" + "A" * 32
        result = sanitize_output(f"Key: {token}")

        assert "sk-" not in result
        assert REDACTED in result

    def test_redacts_google_api_key(self):
        token = "AIza" + "Sy" + "A" * 33
        result = sanitize_output(f"Key: {token}")

        assert "AIza" not in result
        assert REDACTED in result

    def test_redacts_private_key(self):
        text = "-----BEGIN " + "RSA PRIVATE KEY-----\nMIIEpA..."
        result = sanitize_output(text)

        assert "PRIVATE KEY" not in result
        assert REDACTED in result

    def test_redacts_bearer_token(self):
        token = "Bearer " + "eyJ" + "A" * 25
        result = sanitize_output(f"Authorization: {token}")

        assert "eyJ" not in result
        assert REDACTED in result

    def test_preserves_normal_text(self):
        text = "This is a normal code review comment about function naming."
        result = sanitize_output(text)

        assert result == text

    def test_multiple_secrets_redacted(self):
        pat = "glpat-" + "A" * 25
        sk = "sk-" + "A" * 32
        text = f"Found {pat} and {sk} in code"
        result = sanitize_output(text)

        assert "glpat-" not in result
        assert "sk-" not in result
        assert result.count(REDACTED) == 2

    def test_empty_string(self):
        assert sanitize_output("") == ""
