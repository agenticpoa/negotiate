"""Tests for NegotiationAgent.format_prompt placeholder substitution.

The semantic labels (${pro_rata_label}, ${mfn_label}) are the canonical way
to surface required/flexible term constraints to the LLM. The raw boolean
placeholders (${pro_rata_required}, ${mfn_preference}) are kept only for
backcompat with older prompts outside this tree.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from agents.base import NegotiationAgent


@pytest.fixture
def write_prompt(tmp_path):
    def _write(body: str) -> str:
        path = tmp_path / "prompt.txt"
        path.write_text(body)
        return str(path)
    return _write


FLAT_CONSTRAINTS = {
    "valuation_cap_min": 8_000_000,
    "valuation_cap_max": 12_000_000,
    "discount_rate_min": 0.20,
    "discount_rate_max": 0.25,
    "pro_rata_required": True,
    "mfn_required": False,
}


LEGACY_CONSTRAINTS = {
    "valuation_cap": {"min": 8_000_000, "max": 12_000_000},
    "discount_rate": {"min": 0.20, "max": 0.25},
    "pro_rata": {"required": True},
    "mfn": {"required": False},
}


class TestSemanticLabels:
    def test_pro_rata_required_renders_REQUIRED_label(self, write_prompt):
        agent = NegotiationAgent("investor", FLAT_CONSTRAINTS, write_prompt("pro-rata: ${pro_rata_label}"))
        out = agent.format_prompt()
        assert "REQUIRED" in out
        assert "must include pro-rata rights" in out
        assert "Reject any offer that omits them." in out

    def test_pro_rata_not_required_renders_FLEXIBLE_label(self, write_prompt):
        constraints = {**FLAT_CONSTRAINTS, "pro_rata_required": False}
        agent = NegotiationAgent("investor", constraints, write_prompt("pro-rata: ${pro_rata_label}"))
        out = agent.format_prompt()
        assert "FLEXIBLE" in out
        assert "pro-rata rights are not required" in out
        assert "may grant them as a negotiating lever" in out
        assert "NOT a hard prohibition" in out

    def test_mfn_required_renders_REQUIRED_label(self, write_prompt):
        constraints = {**FLAT_CONSTRAINTS, "mfn_required": True}
        agent = NegotiationAgent("investor", constraints, write_prompt("mfn: ${mfn_label}"))
        out = agent.format_prompt()
        assert "REQUIRED" in out
        assert "must include MFN clause" in out

    def test_mfn_not_required_renders_FLEXIBLE_label(self, write_prompt):
        agent = NegotiationAgent("investor", FLAT_CONSTRAINTS, write_prompt("mfn: ${mfn_label}"))
        out = agent.format_prompt()
        assert "FLEXIBLE" in out
        assert "MFN clause are not required" in out

    def test_labels_work_with_legacy_nested_constraints(self, write_prompt):
        body = "pro: ${pro_rata_label}\nmfn: ${mfn_label}"
        agent = NegotiationAgent("investor", LEGACY_CONSTRAINTS, write_prompt(body))
        out = agent.format_prompt()
        assert "REQUIRED" in out  # pro-rata required=True
        assert "FLEXIBLE" in out  # mfn required=False


class TestBackcompatRawBooleans:
    """The raw ${pro_rata_required} / ${mfn_preference} placeholders still work."""

    def test_pro_rata_required_renders_True(self, write_prompt):
        agent = NegotiationAgent("founder", FLAT_CONSTRAINTS, write_prompt("raw: ${pro_rata_required}"))
        assert "raw: True" in agent.format_prompt()

    def test_pro_rata_not_required_renders_False(self, write_prompt):
        constraints = {**FLAT_CONSTRAINTS, "pro_rata_required": False}
        agent = NegotiationAgent("founder", constraints, write_prompt("raw: ${pro_rata_required}"))
        assert "raw: False" in agent.format_prompt()

    def test_mfn_preference_renders_boolean(self, write_prompt):
        agent = NegotiationAgent("founder", FLAT_CONSTRAINTS, write_prompt("raw: ${mfn_preference}"))
        assert "raw: False" in agent.format_prompt()


class TestCurrencyAndPercent:
    def test_currency_and_percent_placeholders(self, write_prompt):
        body = "cap ${cap_min} - ${cap_max}, discount ${discount_min} - ${discount_max}"
        agent = NegotiationAgent("founder", FLAT_CONSTRAINTS, write_prompt(body))
        out = agent.format_prompt()
        assert "$8,000,000" in out
        assert "$12,000,000" in out
        assert "20%" in out
        assert "25%" in out


class TestShippedPromptsUseLabels:
    """The in-tree investor.txt and founder.txt use the semantic labels,
    not the raw booleans, so a deadlock like the APOA / Central Park Labs
    regression cannot recur."""

    def test_investor_prompt_uses_label_placeholders(self):
        body = (Path(__file__).parent.parent / "prompts" / "investor.txt").read_text()
        assert "${pro_rata_label}" in body
        assert "${mfn_label}" in body
        assert "${pro_rata_required}" not in body
        assert "${mfn_preference}" not in body

    def test_founder_prompt_uses_label_placeholders(self):
        body = (Path(__file__).parent.parent / "prompts" / "founder.txt").read_text()
        assert "${pro_rata_label}" in body
        assert "${mfn_label}" in body
        assert "${pro_rata_required}" not in body
        assert "${mfn_preference}" not in body
