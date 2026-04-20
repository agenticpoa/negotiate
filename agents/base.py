"""Base negotiation agent class. Subclass for different LLM backends."""

from __future__ import annotations

from pathlib import Path


class NegotiationAgent:
    """Base class for negotiation agents. Subclass for different LLM backends."""

    def __init__(self, role: str, constraints: dict, prompt_path: str):
        self.role = role
        self.constraints = constraints
        self.prompt = self._load_prompt(prompt_path)

    async def make_offer(self, history: list[dict]) -> dict:
        """Given negotiation history, return an offer dict."""
        raise NotImplementedError

    def _load_prompt(self, path: str) -> str:
        return Path(path).read_text()

    def format_prompt(self) -> str:
        """Fill constraint placeholders in the system prompt.

        Exposes two kinds of placeholders:
          ${pro_rata_required}, ${mfn_preference}  — raw True/False strings
                                                      (legacy; kept for backcompat)
          ${pro_rata_label}, ${mfn_label}          — semantic labels that
                                                      unambiguously tell the
                                                      agent whether a term is
                                                      a hard requirement or a
                                                      flexible negotiating lever.

        Prefer the labels in new prompts. The raw booleans caused LLMs to
        mis-interpret "Pro-rata rights: False" as "forbidden from granting"
        instead of "not required but may be granted", leading to deadlocks
        when one side required pro-rata and the other read it as off-limits.
        """
        prompt = self.prompt

        # Detect format: APOA token (flat keys) vs legacy (nested dicts)
        is_legacy = any(isinstance(v, dict) for v in self.constraints.values())

        if is_legacy:
            pro_rata_required = bool(self.constraints.get("pro_rata", {}).get("required", False))
            mfn_required = bool(self.constraints.get("mfn", {}).get("required", False))
            cap_min = self.constraints.get("valuation_cap", {}).get("min", 0)
            cap_max = self.constraints.get("valuation_cap", {}).get("max", 0)
            discount_min = self.constraints.get("discount_rate", {}).get("min", 0)
            discount_max = self.constraints.get("discount_rate", {}).get("max", 0)
        else:
            pro_rata_required = bool(self.constraints.get("pro_rata_required", False))
            mfn_required = bool(self.constraints.get("mfn_required", False))
            cap_min = self.constraints.get("valuation_cap_min", 0)
            cap_max = self.constraints.get("valuation_cap_max", 0)
            discount_min = self.constraints.get("discount_rate_min", 0)
            discount_max = self.constraints.get("discount_rate_max", 0)

        replacements = {
            "${cap_min}": self._format_currency(cap_min),
            "${cap_max}": self._format_currency(cap_max),
            "${discount_min}": self._format_percent(discount_min),
            "${discount_max}": self._format_percent(discount_max),
            "${pro_rata_required}": str(pro_rata_required),
            "${mfn_preference}": str(mfn_required),
            "${pro_rata_label}": self._term_label("pro-rata rights", pro_rata_required),
            "${mfn_label}": self._term_label("MFN clause", mfn_required),
        }

        for placeholder, value in replacements.items():
            prompt = prompt.replace(placeholder, value)

        return prompt

    @staticmethod
    def _term_label(term: str, required: bool) -> str:
        if required:
            return (
                f"REQUIRED — you must include {term} in any final deal. "
                f"Reject any offer that omits them."
            )
        return (
            f"FLEXIBLE — {term} are not required, but you may grant them "
            f"as a negotiating lever to close the deal. This is NOT a hard "
            f"prohibition; use your judgment."
        )

    @staticmethod
    def _format_currency(value: int | float) -> str:
        return f"${value:,.0f}"

    @staticmethod
    def _format_percent(value: float) -> str:
        return f"{value:.0%}"
