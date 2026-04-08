"""Tests for the negotiation protocol engine."""

import json
from pathlib import Path

import pytest

from protocol import (
    NegotiationState,
    ProtocolSchema,
    validate_offer_structure,
    validate_offer_turn,
)

SCHEMA_PATH = Path(__file__).parent.parent / "schemas" / "safe.json"


@pytest.fixture
def schema():
    return ProtocolSchema.load(SCHEMA_PATH)


@pytest.fixture
def state(schema):
    return NegotiationState(schema=schema)


def _make_offer(from_party="founder", offer_type="offer", **term_overrides):
    terms = {
        "valuation_cap": 10_000_000,
        "discount_rate": 0.20,
        "pro_rata": True,
        "mfn": False,
        **term_overrides,
    }
    return {
        "from": from_party,
        "type": offer_type,
        "terms": terms,
        "message": "Test offer",
    }


class TestOfferStructureValidation:
    def test_valid_offer_passes(self, schema):
        offer = _make_offer()
        valid, reason = validate_offer_structure(offer, schema)
        assert valid
        assert reason == ""

    def test_missing_type_fails(self, schema):
        offer = {"terms": {"valuation_cap": 10_000_000}}
        valid, reason = validate_offer_structure(offer, schema)
        assert not valid
        assert "type" in reason

    def test_invalid_type_fails(self, schema):
        offer = _make_offer(offer_type="negotiate")
        valid, reason = validate_offer_structure(offer, schema)
        assert not valid
        assert "Invalid offer type" in reason

    def test_missing_terms_fails(self, schema):
        offer = {"type": "offer"}
        valid, reason = validate_offer_structure(offer, schema)
        assert not valid
        assert "terms" in reason

    def test_missing_issue_fails(self, schema):
        offer = {
            "type": "offer",
            "terms": {
                "valuation_cap": 10_000_000,
                "discount_rate": 0.20,
                "pro_rata": True,
                # missing mfn
            },
        }
        valid, reason = validate_offer_structure(offer, schema)
        assert not valid
        assert "mfn" in reason

    def test_wrong_type_for_issue_fails(self, schema):
        offer = _make_offer(valuation_cap="ten million")
        valid, reason = validate_offer_structure(offer, schema)
        assert not valid
        assert "Wrong type" in reason

    def test_boolean_as_string_fails(self, schema):
        offer = _make_offer(pro_rata="true")
        valid, reason = validate_offer_structure(offer, schema)
        assert not valid
        assert "Wrong type" in reason

    def test_accept_without_terms_passes(self, schema):
        offer = {"type": "accept"}
        valid, reason = validate_offer_structure(offer, schema)
        assert valid

    def test_reject_without_terms_passes(self, schema):
        offer = {"type": "reject"}
        valid, reason = validate_offer_structure(offer, schema)
        assert valid


class TestRoundTracking:
    def test_initial_round_is_zero(self, state):
        assert state.current_round == 0

    def test_round_increments_on_offer(self, state):
        state.record_offer(_make_offer())
        assert state.current_round == 1

    def test_max_rounds_terminates(self, schema):
        state = NegotiationState(schema=schema)
        parties = ["founder", "investor"]
        for i in range(schema.rules["max_rounds"]):
            state.record_offer(_make_offer(from_party=parties[i % 2]))
        assert state.terminated
        assert state.outcome == "max_rounds"

    def test_accept_terminates(self, state):
        state.record_offer(_make_offer())
        state.record_offer({"type": "accept", "from": "investor"})
        assert state.terminated
        assert state.outcome == "accepted"

    def test_reject_terminates(self, state):
        state.record_offer({"type": "reject", "from": "founder"})
        assert state.terminated
        assert state.outcome == "rejected"


class TestTurnEnforcement:
    def test_founder_goes_first(self, state):
        assert state.whose_turn() == "founder"

    def test_investor_goes_second(self, state):
        state.record_offer(_make_offer())
        assert state.whose_turn() == "investor"

    def test_turn_alternates(self, state):
        state.record_offer(_make_offer(from_party="founder"))
        assert state.whose_turn() == "investor"
        state.record_offer(_make_offer(from_party="investor"))
        assert state.whose_turn() == "founder"

    def test_wrong_turn_fails(self, state):
        offer = _make_offer(from_party="investor")
        valid, reason = validate_offer_turn(offer, state)
        assert not valid
        assert "Expected: founder" in reason


class TestAgreedTerms:
    def test_agreed_terms_on_accept(self, state):
        offer = _make_offer(valuation_cap=9_000_000)
        state.record_offer(offer)
        state.record_offer({"type": "accept", "from": "investor"})
        terms = state.agreed_terms()
        assert terms is not None
        assert terms["valuation_cap"] == 9_000_000

    def test_no_agreed_terms_on_reject(self, state):
        state.record_offer({"type": "reject", "from": "founder"})
        assert state.agreed_terms() is None


class TestSchemaLoading:
    def test_loads_safe_schema(self, schema):
        assert schema.protocol == "apoa-alternating-offers"
        assert schema.document_type == "safe-agreement"
        assert "valuation_cap" in schema.issues
        assert schema.rules["max_rounds"] == 10

    def test_generates_negotiation_id(self, schema):
        assert schema.negotiation_id.startswith("neg_")
        assert len(schema.negotiation_id) > 4
