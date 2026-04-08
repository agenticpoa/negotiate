"""
End-to-end integration test with mock LLM responses.

Verifies the full negotiation flow: offer exchange, validation,
state tracking, document generation, and hash consistency.
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from protocol import (
    NegotiationState,
    ProtocolSchema,
    validate_apoa_constraints,
    validate_offer_structure,
)
from documents.generator import generate_document

SCHEMA_PATH = Path(__file__).parent.parent / "schemas" / "safe.json"

FOUNDER_CONSTRAINTS = {
    "valuation_cap": {"min": 8_000_000, "max": 12_000_000},
    "discount_rate": {"min": 0.20},
    "pro_rata": {"required": True},
}

INVESTOR_CONSTRAINTS = {
    "valuation_cap": {"min": 6_000_000, "max": 10_000_000},
    "discount_rate": {"min": 0.15, "max": 0.25},
    "pro_rata": {"required": False},
}

# Simulated negotiation: 3 rounds then acceptance
MOCK_OFFERS = [
    # Round 0: Founder opens
    {
        "type": "offer",
        "terms": {"valuation_cap": 12_000_000, "discount_rate": 0.20, "pro_rata": True, "mfn": False},
        "message": "Opening offer at $12M cap.",
    },
    # Round 1: Investor counters
    {
        "type": "counter",
        "terms": {"valuation_cap": 7_000_000, "discount_rate": 0.15, "pro_rata": False, "mfn": False},
        "message": "Counter at $7M.",
    },
    # Round 2: Founder counters
    {
        "type": "counter",
        "terms": {"valuation_cap": 9_000_000, "discount_rate": 0.20, "pro_rata": True, "mfn": False},
        "message": "Let's meet in the middle at $9M.",
    },
    # Round 3: Investor accepts
    {
        "type": "accept",
        "message": "Deal. $9M with pro-rata works for us.",
    },
]


class TestEndToEnd:
    def test_full_negotiation_flow(self):
        """Run the full negotiation with mock offers and verify state transitions."""
        schema = ProtocolSchema.load(SCHEMA_PATH)
        state = NegotiationState(schema=schema)

        parties = ["founder", "investor"]
        constraint_map = {
            "founder": FOUNDER_CONSTRAINTS,
            "investor": INVESTOR_CONSTRAINTS,
        }

        logged_offers = []

        for i, mock_offer in enumerate(MOCK_OFFERS):
            current_role = parties[i % 2]
            mock_offer["from"] = current_role
            mock_offer["round"] = state.current_round

            # Validate structure
            valid, reason = validate_offer_structure(mock_offer, schema)
            assert valid, f"Round {i} structure invalid: {reason}"

            # Validate constraints (skip for accept/reject)
            if mock_offer["type"] in ("offer", "counter"):
                valid, violations = validate_apoa_constraints(
                    mock_offer["terms"], constraint_map[current_role],
                )
                assert valid, f"Round {i} APOA violation: {violations}"

            logged_offers.append(mock_offer)
            state.record_offer(mock_offer)

        assert state.terminated
        assert state.outcome == "accepted"
        assert len(logged_offers) == 4

    def test_offers_logged_in_order(self):
        """Verify the chain of offers is in correct order."""
        schema = ProtocolSchema.load(SCHEMA_PATH)
        state = NegotiationState(schema=schema)
        parties = ["founder", "investor"]

        for i, mock_offer in enumerate(MOCK_OFFERS):
            mock_offer["from"] = parties[i % 2]
            mock_offer["round"] = state.current_round
            state.record_offer(mock_offer)

        assert len(state.history) == 4
        assert state.history[0]["from"] == "founder"
        assert state.history[1]["from"] == "investor"
        assert state.history[2]["from"] == "founder"
        assert state.history[3]["from"] == "investor"

    def test_agreement_triggers_document_generation(self):
        """On accept, document generation should succeed with agreed terms."""
        schema = ProtocolSchema.load(SCHEMA_PATH)
        state = NegotiationState(schema=schema)
        parties_list = ["founder", "investor"]

        for i, mock_offer in enumerate(MOCK_OFFERS):
            mock_offer["from"] = parties_list[i % 2]
            mock_offer["round"] = state.current_round
            state.record_offer(mock_offer)

        agreed = state.agreed_terms()
        assert agreed is not None

        terms = {
            **agreed,
            "date": "2026-04-01",
            "investment_amount": 500_000.0,
        }
        parties = {
            "founder": {"company": "Acme Corp", "name": "Jane Doe", "title": "CEO"},
            "investor": {"name": "Angel Ventures"},
        }

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            path = f.name
        try:
            doc_hash = generate_document("safe-agreement", terms, parties, path)
            assert len(doc_hash) == 64
            assert os.path.exists(path)
        finally:
            os.unlink(path)

    def test_document_hash_is_deterministic(self):
        """Same agreed terms always produce the same document hash."""
        terms = {
            "valuation_cap": 9_000_000,
            "discount_rate": 0.20,
            "pro_rata": True,
            "mfn": False,
            "date": "2026-04-01",
            "investment_amount": 500_000.0,
        }
        parties = {
            "founder": {"company": "Acme Corp", "name": "Jane Doe", "title": "CEO"},
            "investor": {"name": "Angel Ventures"},
        }

        hashes = []
        paths = []
        for _ in range(2):
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
                path = f.name
            paths.append(path)
            hashes.append(generate_document("safe-agreement", terms, parties, path))

        try:
            assert hashes[0] == hashes[1], "Document hash must be deterministic"
        finally:
            for p in paths:
                os.unlink(p)

    def test_max_rounds_without_agreement(self):
        """If agents never agree, negotiation terminates at max rounds."""
        schema = ProtocolSchema.load(SCHEMA_PATH)
        state = NegotiationState(schema=schema)
        parties = ["founder", "investor"]

        for i in range(schema.rules["max_rounds"]):
            offer = {
                "type": "counter" if i > 0 else "offer",
                "from": parties[i % 2],
                "terms": {
                    "valuation_cap": 10_000_000,
                    "discount_rate": 0.20,
                    "pro_rata": True,
                    "mfn": False,
                },
                "message": f"Round {i}",
            }
            state.record_offer(offer)

        assert state.terminated
        assert state.outcome == "max_rounds"
        assert state.agreed_terms() is None
