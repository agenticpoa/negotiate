"""Tests for --json-events structured output."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "negotiate.py"


class TestJsonEventsFlag:
    def test_flag_accepted(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--help"],
            capture_output=True, text=True,
        )
        assert "--json-events" in result.stdout


class TestEmitJsonEvent:
    def test_offer_event_has_required_fields(self):
        from negotiate import emit_json_event
        import io

        offer = {
            "type": "offer",
            "terms": {"valuation_cap": 10_000_000, "discount_rate": 0.20, "pro_rata": True, "mfn": False},
            "message": "Counter at $10M.",
            "immudb_tx": 48326,
            "timestamp": "2026-04-18T00:00:00Z",
        }
        buf = io.StringIO()
        emit_json_event(buf, offer, "founder", 2)
        line = buf.getvalue().strip()
        event = json.loads(line)

        assert event["type"] == "offer"
        assert event["round"] == 2
        assert event["party"] == "founder"
        assert event["terms"]["valuation_cap"] == 10_000_000
        assert event["message"] == "Counter at $10M."
        assert event["immudb_tx"] == 48326

    def test_accept_event(self):
        from negotiate import emit_json_event
        import io

        offer = {"type": "accept", "message": "Deal."}
        buf = io.StringIO()
        emit_json_event(buf, offer, "investor", 5)
        event = json.loads(buf.getvalue())
        assert event["type"] == "accept"
        assert event["party"] == "investor"

    def test_outcome_event_agreement(self):
        from negotiate import emit_outcome_event
        import io

        buf = io.StringIO()
        emit_outcome_event(buf, "accepted", {"valuation_cap": 9_000_000, "discount_rate": 0.15}, 24.5)
        event = json.loads(buf.getvalue())
        assert event["type"] == "outcome"
        assert event["result"] == "accepted"
        assert event["terms"]["valuation_cap"] == 9_000_000
        assert event["duration_seconds"] == 24.5

    def test_outcome_event_deadlock(self):
        from negotiate import emit_outcome_event
        import io

        buf = io.StringIO()
        emit_outcome_event(buf, "max_rounds", None, 60.0)
        event = json.loads(buf.getvalue())
        assert event["result"] == "max_rounds"
        assert event["terms"] is None
