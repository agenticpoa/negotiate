"""Tests for APOA constraint validation."""

import pytest

from protocol import validate_apoa_constraints


FOUNDER_CONSTRAINTS = {
    "valuation_cap": {"min": 8_000_000, "max": 12_000_000},
    "discount_rate": {"min": 0.20},
    "pro_rata": {"required": True},
}

# APOA token format (flat keys from ServiceAuthorization.constraints)
FOUNDER_TOKEN_CONSTRAINTS = {
    "valuation_cap_min": 8_000_000,
    "valuation_cap_max": 12_000_000,
    "discount_rate_min": 0.20,
    "pro_rata_required": True,
}


class TestConstraintValidation:
    def test_valid_offer_passes(self):
        terms = {
            "valuation_cap": 10_000_000,
            "discount_rate": 0.20,
            "pro_rata": True,
            "mfn": False,
        }
        valid, violations = validate_apoa_constraints(terms, FOUNDER_CONSTRAINTS)
        assert valid
        assert violations == []

    def test_cap_below_minimum_fails(self):
        terms = {
            "valuation_cap": 5_000_000,
            "discount_rate": 0.20,
            "pro_rata": True,
            "mfn": False,
        }
        valid, violations = validate_apoa_constraints(terms, FOUNDER_CONSTRAINTS)
        assert not valid
        assert any("below minimum" in v for v in violations)

    def test_cap_above_maximum_fails(self):
        terms = {
            "valuation_cap": 15_000_000,
            "discount_rate": 0.20,
            "pro_rata": True,
            "mfn": False,
        }
        valid, violations = validate_apoa_constraints(terms, FOUNDER_CONSTRAINTS)
        assert not valid
        assert any("above maximum" in v for v in violations)

    def test_cap_at_minimum_passes(self):
        terms = {
            "valuation_cap": 8_000_000,
            "discount_rate": 0.20,
            "pro_rata": True,
            "mfn": False,
        }
        valid, _ = validate_apoa_constraints(terms, FOUNDER_CONSTRAINTS)
        assert valid

    def test_cap_at_maximum_passes(self):
        terms = {
            "valuation_cap": 12_000_000,
            "discount_rate": 0.20,
            "pro_rata": True,
            "mfn": False,
        }
        valid, _ = validate_apoa_constraints(terms, FOUNDER_CONSTRAINTS)
        assert valid

    def test_discount_below_minimum_fails(self):
        terms = {
            "valuation_cap": 10_000_000,
            "discount_rate": 0.10,
            "pro_rata": True,
            "mfn": False,
        }
        valid, violations = validate_apoa_constraints(terms, FOUNDER_CONSTRAINTS)
        assert not valid
        assert any("discount_rate" in v for v in violations)

    def test_pro_rata_false_when_required_fails(self):
        terms = {
            "valuation_cap": 10_000_000,
            "discount_rate": 0.20,
            "pro_rata": False,
            "mfn": False,
        }
        valid, violations = validate_apoa_constraints(terms, FOUNDER_CONSTRAINTS)
        assert not valid
        assert any("pro_rata" in v for v in violations)

    def test_multiple_violations_reported(self):
        terms = {
            "valuation_cap": 5_000_000,
            "discount_rate": 0.10,
            "pro_rata": False,
            "mfn": False,
        }
        valid, violations = validate_apoa_constraints(terms, FOUNDER_CONSTRAINTS)
        assert not valid
        assert len(violations) == 3

    def test_no_constraints_means_everything_passes(self):
        terms = {"valuation_cap": 1, "pro_rata": False}
        valid, violations = validate_apoa_constraints(terms, {})
        assert valid
        assert violations == []

    def test_missing_constrained_field_fails(self):
        terms = {"discount_rate": 0.20, "pro_rata": True, "mfn": False}
        valid, violations = validate_apoa_constraints(terms, FOUNDER_CONSTRAINTS)
        assert not valid
        assert any("Missing" in v for v in violations)


class TestTokenConstraintFormat:
    """Tests for APOA token constraint format (flat keys)."""

    def test_valid_offer_passes(self):
        terms = {
            "valuation_cap": 10_000_000,
            "discount_rate": 0.20,
            "pro_rata": True,
            "mfn": False,
        }
        valid, violations = validate_apoa_constraints(terms, FOUNDER_TOKEN_CONSTRAINTS)
        assert valid
        assert violations == []

    def test_cap_below_minimum_fails(self):
        terms = {
            "valuation_cap": 5_000_000,
            "discount_rate": 0.20,
            "pro_rata": True,
            "mfn": False,
        }
        valid, violations = validate_apoa_constraints(terms, FOUNDER_TOKEN_CONSTRAINTS)
        assert not valid
        assert any("below minimum" in v for v in violations)

    def test_cap_above_maximum_fails(self):
        terms = {
            "valuation_cap": 15_000_000,
            "discount_rate": 0.20,
            "pro_rata": True,
            "mfn": False,
        }
        valid, violations = validate_apoa_constraints(terms, FOUNDER_TOKEN_CONSTRAINTS)
        assert not valid
        assert any("above maximum" in v for v in violations)

    def test_discount_below_minimum_fails(self):
        terms = {
            "valuation_cap": 10_000_000,
            "discount_rate": 0.10,
            "pro_rata": True,
            "mfn": False,
        }
        valid, violations = validate_apoa_constraints(terms, FOUNDER_TOKEN_CONSTRAINTS)
        assert not valid
        assert any("discount_rate" in v for v in violations)

    def test_pro_rata_false_when_required_fails(self):
        terms = {
            "valuation_cap": 10_000_000,
            "discount_rate": 0.20,
            "pro_rata": False,
            "mfn": False,
        }
        valid, violations = validate_apoa_constraints(terms, FOUNDER_TOKEN_CONSTRAINTS)
        assert not valid
        assert any("pro_rata" in v for v in violations)

    def test_at_boundaries_passes(self):
        terms = {
            "valuation_cap": 8_000_000,
            "discount_rate": 0.20,
            "pro_rata": True,
            "mfn": False,
        }
        valid, _ = validate_apoa_constraints(terms, FOUNDER_TOKEN_CONSTRAINTS)
        assert valid

    def test_multiple_violations(self):
        terms = {
            "valuation_cap": 5_000_000,
            "discount_rate": 0.10,
            "pro_rata": False,
            "mfn": False,
        }
        valid, violations = validate_apoa_constraints(terms, FOUNDER_TOKEN_CONSTRAINTS)
        assert not valid
        assert len(violations) == 3
