"""Claude-powered negotiation agent using the Anthropic Python SDK."""

from __future__ import annotations

import json
import logging

import anthropic

from agents.base import NegotiationAgent

logger = logging.getLogger(__name__)

MAX_RETRIES = 3


class ClaudeAgent(NegotiationAgent):
    """Negotiation agent backed by Claude via the Anthropic API."""

    def __init__(
        self,
        role: str,
        constraints: dict,
        prompt_path: str,
        model: str = "claude-sonnet-4-20250514",
    ):
        super().__init__(role, constraints, prompt_path)
        self.client = anthropic.AsyncAnthropic()
        self.model = model

    async def make_offer(self, history: list[dict]) -> dict:
        """Call Claude with the system prompt and conversation history, parse JSON response."""
        system_prompt = self.format_prompt()
        messages = self._build_messages(history)

        for attempt in range(MAX_RETRIES):
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                system=system_prompt,
                messages=messages,
            )

            text = response.content[0].text.strip()

            # Strip markdown code fences if present
            if text.startswith("```"):
                lines = text.split("\n")
                lines = [l for l in lines if not l.startswith("```")]
                text = "\n".join(lines).strip()

            try:
                offer = json.loads(text)
                return offer
            except json.JSONDecodeError as e:
                logger.warning(
                    "Attempt %d/%d: Failed to parse JSON from %s: %s",
                    attempt + 1, MAX_RETRIES, self.role, e,
                )
                # Feed error back to the LLM for retry
                messages.append({"role": "assistant", "content": text})
                messages.append({
                    "role": "user",
                    "content": (
                        f"Your response was not valid JSON (error: {e}). "
                        "Respond ONLY with the JSON object, no other text."
                    ),
                })

        raise ValueError(
            f"Agent '{self.role}' failed to produce valid JSON after {MAX_RETRIES} attempts"
        )

    def _build_messages(self, history: list[dict]) -> list[dict]:
        """Convert negotiation history into Claude message format."""
        messages = []

        for entry in history:
            sender = entry.get("from", "")
            content = json.dumps(entry, indent=2)

            if sender == self.role:
                messages.append({"role": "assistant", "content": content})
            else:
                messages.append({"role": "user", "content": content})

        # If no history or last message was from this agent, add a user prompt
        if not messages or messages[-1]["role"] == "assistant":
            if not history:
                messages.append({
                    "role": "user",
                    "content": "The negotiation is starting. Please make your opening offer.",
                })
            else:
                messages.append({
                    "role": "user",
                    "content": "Please respond to the above offer.",
                })

        return messages
