"""Tests for the signer_role config field.

`signer_role` is deliberately decoupled from `role`:
  - `role`        determines dispatch between run_local vs run_distributed
  - `signer_role` determines which *_pending.txt file is written and which
                  label lands on the executed PDF

This lets local-mode callers (the claw-negotiate dual-role demo) record
the correct signer when the user plays investor rather than founder.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from negotiate import NegotiationConfig


@pytest.fixture
def base_kwargs(tmp_path):
    return dict(
        negotiate_repo=tmp_path,
        negotiation_id="neg_test",
        founder_token_path=str(tmp_path / "f.jwt"),
        investor_token_path=str(tmp_path / "i.jwt"),
        founder_pubkey_path=str(tmp_path / "f.pem"),
        investor_pubkey_path=str(tmp_path / "i.pem"),
        company_name="Acme",
        founder_name="Jane",
        investor_name="Ven",
    )


class TestNegotiationConfigSignerRole:
    def test_default_is_empty_string(self, base_kwargs):
        cfg = NegotiationConfig(**base_kwargs)
        assert cfg.signer_role == ""

    def test_accepts_explicit_value(self, base_kwargs):
        cfg = NegotiationConfig(**base_kwargs, signer_role="investor")
        assert cfg.signer_role == "investor"

    def test_to_namespace_propagates_signer_role(self, base_kwargs):
        cfg = NegotiationConfig(**base_kwargs, signer_role="investor")
        ns = cfg.to_namespace()
        assert ns.signer_role == "investor"

    def test_to_namespace_preserves_empty_signer_role(self, base_kwargs):
        cfg = NegotiationConfig(**base_kwargs)
        ns = cfg.to_namespace()
        assert ns.signer_role == ""

    def test_signer_role_independent_of_role(self, base_kwargs):
        """Can set signer_role without triggering distributed-mode dispatch."""
        cfg = NegotiationConfig(**base_kwargs, signer_role="investor", role="")
        ns = cfg.to_namespace()
        assert ns.role == ""  # stays local
        assert ns.signer_role == "investor"
