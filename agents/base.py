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
        """Fill constraint placeholders in the system prompt."""
        prompt = self.prompt

        # Detect format: APOA token (flat keys) vs legacy (nested dicts)
        is_legacy = any(isinstance(v, dict) for v in self.constraints.values())

        if is_legacy:
            replacements = {
                "${cap_min}": self._format_currency(self.constraints.get("valuation_cap", {}).get("min", 0)),
                "${cap_max}": self._format_currency(self.constraints.get("valuation_cap", {}).get("max", 0)),
                "${discount_min}": self._format_percent(self.constraints.get("discount_rate", {}).get("min", 0)),
                "${discount_max}": self._format_percent(self.constraints.get("discount_rate", {}).get("max", 0)),
                "${pro_rata_required}": str(self.constraints.get("pro_rata", {}).get("required", False)),
                "${mfn_preference}": str(self.constraints.get("mfn", {}).get("required", False)),
            }
        else:
            replacements = {
                "${cap_min}": self._format_currency(self.constraints.get("valuation_cap_min", 0)),
                "${cap_max}": self._format_currency(self.constraints.get("valuation_cap_max", 0)),
                "${discount_min}": self._format_percent(self.constraints.get("discount_rate_min", 0)),
                "${discount_max}": self._format_percent(self.constraints.get("discount_rate_max", 0)),
                "${pro_rata_required}": str(self.constraints.get("pro_rata_required", False)),
                "${mfn_preference}": str(self.constraints.get("mfn_required", False)),
            }

        for placeholder, value in replacements.items():
            prompt = prompt.replace(placeholder, value)

        return prompt

    @staticmethod
    def _format_currency(value: int | float) -> str:
        return f"${value:,.0f}"

    @staticmethod
    def _format_percent(value: float) -> str:
        return f"{value:.0%}"
