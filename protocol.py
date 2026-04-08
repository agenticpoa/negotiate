"""
APOA Alternating Offers Protocol engine.

Handles schema loading, offer validation, round tracking, turn enforcement,
and APOA constraint checking. Based on Rubinstein (1982) alternating offers
with multi-issue extension per Fatima/Kraus/Wooldridge (2014).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


VALID_OFFER_TYPES = {"offer", "counter", "accept", "reject"}
TYPE_MAP = {"number": (int, float), "boolean": bool}


@dataclass
class ProtocolSchema:
    protocol: str
    version: str
    based_on: str
    negotiation_id: str
    document_type: str
    issues: dict[str, dict[str, str]]
    rules: dict[str, Any]

    @classmethod
    def load(cls, path: str | Path) -> ProtocolSchema:
        with open(path) as f:
            data = json.load(f)

        neg_id = data.get("negotiation_id", "")
        if neg_id == "neg_<uuid>" or not neg_id:
            neg_id = f"neg_{uuid.uuid4().hex[:12]}"

        return cls(
            protocol=data["protocol"],
            version=data["version"],
            based_on=data.get("based_on", ""),
            negotiation_id=neg_id,
            document_type=data["document_type"],
            issues=data["issues"],
            rules=data["rules"],
        )


@dataclass
class NegotiationState:
    schema: ProtocolSchema
    history: list[dict] = field(default_factory=list)
    current_round: int = 0
    terminated: bool = False
    outcome: str | None = None  # "accepted", "rejected", "max_rounds"

    @property
    def max_rounds(self) -> int:
        return self.schema.rules["max_rounds"]

    @property
    def first_mover(self) -> str:
        return self.schema.rules["first_mover"]

    def whose_turn(self) -> str:
        parties = ["founder", "investor"]
        if self.first_mover == "investor":
            parties = ["investor", "founder"]
        return parties[self.current_round % 2]

    def record_offer(self, offer: dict) -> None:
        self.history.append(offer)
        if offer["type"] == "accept":
            self.terminated = True
            self.outcome = "accepted"
        elif offer["type"] == "reject":
            self.terminated = True
            self.outcome = "rejected"
        else:
            self.current_round += 1
            if self.current_round >= self.max_rounds:
                self.terminated = True
                self.outcome = "max_rounds"

    def last_offer(self) -> dict | None:
        if not self.history:
            return None
        return self.history[-1]

    def agreed_terms(self) -> dict | None:
        if self.outcome != "accepted" or len(self.history) < 2:
            return None
        # The accepted terms are from the previous offer (the one being accepted)
        return self.history[-2]["terms"]


def validate_offer_structure(offer: dict, schema: ProtocolSchema) -> tuple[bool, str]:
    """Validate that an offer has all required fields with correct types."""
    if "type" not in offer:
        return False, "Missing 'type' field"

    if offer["type"] not in VALID_OFFER_TYPES:
        return False, f"Invalid offer type: {offer['type']}. Must be one of {VALID_OFFER_TYPES}"

    # accept and reject don't need terms
    if offer["type"] in ("accept", "reject"):
        return True, ""

    if "terms" not in offer:
        return False, "Missing 'terms' field"

    terms = offer["terms"]

    for issue_name, issue_def in schema.issues.items():
        if issue_name not in terms:
            return False, f"Missing required issue: {issue_name}"

        expected_types = TYPE_MAP.get(issue_def["type"])
        if expected_types and not isinstance(terms[issue_name], expected_types):
            return False, (
                f"Wrong type for '{issue_name}': expected {issue_def['type']}, "
                f"got {type(terms[issue_name]).__name__}"
            )

    return True, ""


def validate_offer_turn(offer: dict, state: NegotiationState) -> tuple[bool, str]:
    """Validate that it's the correct party's turn."""
    expected = state.whose_turn()
    from_party = offer.get("from", "")
    if from_party and from_party != expected:
        return False, f"Not {from_party}'s turn. Expected: {expected}"
    return True, ""


def validate_apoa_constraints(terms: dict, constraints: dict) -> tuple[bool, list[str]]:
    """
    Validate offer terms against APOA constraints.

    Supports two formats:

    Legacy dict format (for backwards compatibility with tests):
        {
            "valuation_cap": {"min": 8000000, "max": 12000000},
            "discount_rate": {"min": 0.20},
            "pro_rata": {"required": True},
        }

    APOA token constraint format (from ServiceAuthorization.constraints):
        {
            "valuation_cap_min": 8000000,
            "valuation_cap_max": 12000000,
            "discount_rate_min": 0.20,
            "pro_rata_required": True,
        }

    Returns (valid, list_of_violations).
    """
    violations = []

    # Detect format: if any value is a dict, it's legacy format
    is_legacy = any(isinstance(v, dict) for v in constraints.values())

    if is_legacy:
        for field_name, rules in constraints.items():
            if field_name not in terms:
                violations.append(f"Missing constrained field: {field_name}")
                continue

            value = terms[field_name]

            if "min" in rules and isinstance(value, (int, float)):
                if value < rules["min"]:
                    violations.append(
                        f"{field_name}: {value} is below minimum {rules['min']}"
                    )

            if "max" in rules and isinstance(value, (int, float)):
                if value > rules["max"]:
                    violations.append(
                        f"{field_name}: {value} is above maximum {rules['max']}"
                    )

            if "required" in rules and isinstance(value, bool):
                if rules["required"] and not value:
                    violations.append(
                        f"{field_name}: required to be true but is false"
                    )
    else:
        # APOA token format: flat keys like valuation_cap_min, valuation_cap_max
        for key, constraint_value in constraints.items():
            if key.endswith("_min"):
                field = key.removesuffix("_min")
                if field not in terms:
                    violations.append(f"Missing constrained field: {field}")
                    continue
                value = terms[field]
                if isinstance(value, (int, float)) and value < constraint_value:
                    violations.append(
                        f"{field}: {value} is below minimum {constraint_value}"
                    )
            elif key.endswith("_max"):
                field = key.removesuffix("_max")
                if field not in terms:
                    continue
                value = terms[field]
                if isinstance(value, (int, float)) and value > constraint_value:
                    violations.append(
                        f"{field}: {value} is above maximum {constraint_value}"
                    )
            elif key.endswith("_required"):
                field = key.removesuffix("_required")
                if field not in terms:
                    violations.append(f"Missing constrained field: {field}")
                    continue
                value = terms[field]
                if constraint_value and isinstance(value, bool) and not value:
                    violations.append(
                        f"{field}: required to be true but is false"
                    )

    return (len(violations) == 0, violations)
