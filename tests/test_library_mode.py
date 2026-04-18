"""Tests for library-mode entry point (NegotiationConfig + run_negotiation)."""
from __future__ import annotations

import pytest
from pathlib import Path


class TestNegotiationConfig:
    def test_import(self):
        from negotiate import NegotiationConfig
        assert NegotiationConfig is not None

    def test_required_fields(self):
        from negotiate import NegotiationConfig
        config = NegotiationConfig(
            negotiate_repo=Path("/tmp/repo"),
            negotiation_id="neg_test",
            founder_token_path="/tmp/founder.jwt",
            investor_token_path="/tmp/investor.jwt",
            founder_pubkey_path="/tmp/founder.pem",
            investor_pubkey_path="/tmp/investor.pem",
            company_name="Acme",
            founder_name="Jane",
            investor_name="Bob",
        )
        assert config.negotiation_id == "neg_test"
        assert config.company_name == "Acme"

    def test_defaults(self):
        from negotiate import NegotiationConfig
        config = NegotiationConfig(
            negotiate_repo=Path("/tmp"),
            negotiation_id="neg_1",
            founder_token_path="f.jwt",
            investor_token_path="i.jwt",
            founder_pubkey_path="f.pem",
            investor_pubkey_path="i.pem",
            company_name="Co",
            founder_name="F",
            investor_name="I",
        )
        assert config.sshsign_host == "sshsign.dev"
        assert config.no_sshsign is False
        assert config.output_dir == "output"
        assert config.poll is True
        assert config.json_events is False
        assert config.founder_title == ""
        assert config.investor_firm == ""
        assert config.investment_amount == 500_000.0

    def test_to_namespace(self):
        from negotiate import NegotiationConfig
        config = NegotiationConfig(
            negotiate_repo=Path("/tmp/repo"),
            negotiation_id="neg_ns",
            founder_token_path="/tmp/f.jwt",
            investor_token_path="/tmp/i.jwt",
            founder_pubkey_path="/tmp/f.pem",
            investor_pubkey_path="/tmp/i.pem",
            company_name="Acme",
            founder_name="Jane",
            investor_name="Bob",
            output_dir="/tmp/output",
            json_events=True,
        )
        ns = config.to_namespace()
        assert ns.negotiation_id == "neg_ns"
        assert ns.founder_token == "/tmp/f.jwt"
        assert ns.investor_token == "/tmp/i.jwt"
        assert ns.company_name == "Acme"
        assert ns.output_dir == "/tmp/output"
        assert ns.json_events is True
        assert ns.schema == str(Path("/tmp/repo") / "schemas" / "safe.json")


class TestRunNegotiation:
    def test_import(self):
        from negotiate import run_negotiation
        assert callable(run_negotiation)
