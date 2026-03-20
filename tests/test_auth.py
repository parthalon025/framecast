"""Tests for app/modules/auth.py — PIN verification, rate limiting, HMAC, open access."""

import hmac
import hashlib
import json
import os
import sys

import pytest

# app/ is already on sys.path via conftest.py


@pytest.fixture(autouse=True)
def _reset_auth_state(monkeypatch):
    """Isolate auth module state between tests.

    Patches config.get so auth reads our test values instead of a real .env,
    and resets the rate limiters between tests.
    """
    # Default test config values
    _cfg = {
        "ACCESS_PIN": "1234",
        "FLASK_SECRET_KEY": "test-secret-key",
        "PIN_LENGTH": "4",
    }

    def fake_config_get(key, default=""):
        return _cfg.get(key, default)

    monkeypatch.setattr("modules.config.get", fake_config_get)

    # Expose the config dict so individual tests can mutate it
    yield _cfg

    # Reset rate limiter state between tests
    import modules.auth as auth
    auth._pin_limiter_4._counts.clear()
    auth._pin_limiter_6._counts.clear()


@pytest.fixture
def auth_mod():
    """Return the auth module."""
    import modules.auth as mod
    return mod


@pytest.fixture
def app(auth_mod):
    """Minimal Flask app with the auth blueprint registered."""
    from flask import Flask
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(auth_mod.auth_api)
    return app


@pytest.fixture
def client(app):
    """Flask test client."""
    return app.test_client()


# ---------------------------------------------------------------------------
# PIN verification tests
# ---------------------------------------------------------------------------


class TestVerifyPin:
    """Tests for the /api/auth/verify endpoint."""

    def test_verify_correct_pin(self, client):
        """Correct PIN returns 200 with 'ok' status."""
        resp = client.post(
            "/api/auth/verify",
            data=json.dumps({"pin": "1234"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["status"] == "ok"
        assert body["message"] == "AUTHORIZED"

    def test_verify_wrong_pin(self, client):
        """Wrong PIN returns 401 with needs_pin flag."""
        resp = client.post(
            "/api/auth/verify",
            data=json.dumps({"pin": "9999"}),
            content_type="application/json",
        )
        assert resp.status_code == 401
        body = resp.get_json()
        assert body["needs_pin"] is True

    def test_verify_rate_limited(self, client):
        """Too many wrong attempts triggers 429 rate limiting.

        4-digit PIN has max_attempts=5, so the 6th attempt should be blocked.
        """
        for _ in range(5):
            client.post(
                "/api/auth/verify",
                data=json.dumps({"pin": "0000"}),
                content_type="application/json",
            )

        # 6th attempt should be rate limited
        resp = client.post(
            "/api/auth/verify",
            data=json.dumps({"pin": "0000"}),
            content_type="application/json",
        )
        assert resp.status_code == 429
        body = resp.get_json()
        assert "retry_after" in body
        assert body["retry_after"] > 0

    def test_empty_pin_open_access(self, client, _reset_auth_state):
        """Empty ACCESS_PIN means open access — verify succeeds without checking PIN value."""
        _reset_auth_state["ACCESS_PIN"] = ""

        resp = client.post(
            "/api/auth/verify",
            data=json.dumps({"pin": "anything"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["status"] == "ok"
        assert "open access" in body["message"].lower()


# ---------------------------------------------------------------------------
# HMAC token tests
# ---------------------------------------------------------------------------


class TestHmacToken:
    """Tests for the auth token derivation."""

    def test_hmac_token_not_raw_pin(self, auth_mod):
        """Auth token must differ from the raw PIN — HMAC derivation, not plaintext."""
        token = auth_mod._make_auth_token("1234")
        assert token != "1234"
        # Should look like a hex digest (64 chars for SHA-256)
        assert len(token) == 64
        assert all(c in "0123456789abcdef" for c in token)


# ---------------------------------------------------------------------------
# PIN length validation tests
# ---------------------------------------------------------------------------


class TestPinLength:
    """Tests for PIN_LENGTH configuration validation."""

    def test_pin_length_valid_4(self, auth_mod, _reset_auth_state):
        """PIN_LENGTH=4 is accepted."""
        _reset_auth_state["PIN_LENGTH"] = "4"
        assert auth_mod._get_pin_length() == 4

    def test_pin_length_valid_6(self, auth_mod, _reset_auth_state):
        """PIN_LENGTH=6 is accepted."""
        _reset_auth_state["PIN_LENGTH"] = "6"
        assert auth_mod._get_pin_length() == 6

    def test_pin_length_invalid_defaults_to_4(self, auth_mod, _reset_auth_state):
        """Invalid PIN_LENGTH (not 4 or 6) defaults to 4."""
        _reset_auth_state["PIN_LENGTH"] = "8"
        assert auth_mod._get_pin_length() == 4

    def test_pin_length_non_numeric_defaults_to_4(self, auth_mod, _reset_auth_state):
        """Non-numeric PIN_LENGTH defaults to 4."""
        _reset_auth_state["PIN_LENGTH"] = "abc"
        assert auth_mod._get_pin_length() == 4
