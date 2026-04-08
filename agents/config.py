"""Agent configuration loading."""

from __future__ import annotations

# Default APOA constraints for the founder agent
DEFAULT_FOUNDER_CONSTRAINTS = {
    "valuation_cap": {"min": 8_000_000, "max": 12_000_000},
    "discount_rate": {"min": 0.20, "max": 0.25},
    "pro_rata": {"required": True},
    "mfn": {"required": False},
}

# Default preferences for the investor agent (softer constraints)
DEFAULT_INVESTOR_CONSTRAINTS = {
    "valuation_cap": {"min": 6_000_000, "max": 10_000_000},
    "discount_rate": {"min": 0.15, "max": 0.25},
    "pro_rata": {"required": False},
    "mfn": {"required": False},
}


def build_founder_constraints(
    cap_min: int = 8_000_000,
    cap_max: int = 12_000_000,
    discount_min: float = 0.20,
    discount_max: float = 0.25,
    pro_rata_required: bool = True,
    mfn_required: bool = False,
) -> dict:
    return {
        "valuation_cap": {"min": cap_min, "max": cap_max},
        "discount_rate": {"min": discount_min, "max": discount_max},
        "pro_rata": {"required": pro_rata_required},
        "mfn": {"required": mfn_required},
    }


def build_investor_constraints(
    cap_min: int = 6_000_000,
    cap_max: int = 10_000_000,
    discount_min: float = 0.15,
    discount_max: float = 0.25,
    pro_rata_required: bool = False,
    mfn_required: bool = False,
) -> dict:
    return {
        "valuation_cap": {"min": cap_min, "max": cap_max},
        "discount_rate": {"min": discount_min, "max": discount_max},
        "pro_rata": {"required": pro_rata_required},
        "mfn": {"required": mfn_required},
    }
