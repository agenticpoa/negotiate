"""Tests for create_tokens.py CLI flags and token creation."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parent.parent / "create_tokens.py"


class TestServiceFlag:
    def test_service_flag_accepted(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--help"],
            capture_output=True, text=True,
        )
        assert "--service" in result.stdout, (
            "create_tokens.py should accept a --service flag for per-negotiation scope"
        )

    def test_service_defaults_to_safe_agreement(self, tmp_path):
        """Without --service, the token's service field should be 'safe-agreement'."""
        result = subprocess.run(
            [sys.executable, str(SCRIPT),
             "--keys-dir", str(tmp_path / "keys"),
             "--tokens-dir", str(tmp_path / "tokens"),
             "--config-dir", str(tmp_path),
             "--negotiation-id", "neg_test",
             "--principal-id", "did:apoa:test",
             ],
            capture_output=True, text=True,
            cwd=str(SCRIPT.parent),
        )
        assert result.returncode == 0, result.stderr
        token_path = tmp_path / "tokens" / "founder.jwt"
        assert token_path.exists()

        import base64
        jwt = token_path.read_text().strip()
        payload_b64 = jwt.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        service = payload["definition"]["services"][0]["service"]
        assert service == "safe-agreement"

    def test_custom_service_in_token(self, tmp_path):
        """With --service, the token should use the custom value."""
        result = subprocess.run(
            [sys.executable, str(SCRIPT),
             "--keys-dir", str(tmp_path / "keys"),
             "--tokens-dir", str(tmp_path / "tokens"),
             "--config-dir", str(tmp_path),
             "--negotiation-id", "neg_test",
             "--principal-id", "did:apoa:test",
             "--service", "safe:acme:neg_test",
             ],
            capture_output=True, text=True,
            cwd=str(SCRIPT.parent),
        )
        assert result.returncode == 0, result.stderr

        import base64
        token_path = tmp_path / "tokens" / "founder.jwt"
        jwt = token_path.read_text().strip()
        payload_b64 = jwt.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        service = payload["definition"]["services"][0]["service"]
        assert service == "safe:acme:neg_test"
