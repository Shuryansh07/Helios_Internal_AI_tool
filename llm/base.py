"""
Unified entry point for all LLM providers.

Each provider takes the same arguments (system prompt + user prompt) and returns
plain text. The web app picks the provider from the chat dropdown.
"""
import os

from . import openai_provider, gemini_provider, claude_provider

_PROVIDERS = {
    "openai": openai_provider,
    "gemini": gemini_provider,
    "claude": claude_provider,
}


def available_providers():
    """Return which providers have an API key configured, for the UI dropdown."""
    return {
        "openai": bool(os.getenv("OPENAI_API_KEY")),
        "gemini": bool(os.getenv("GEMINI_API_KEY")),
        "claude": bool(os.getenv("CLAUDE_API_KEY")),
    }


def generate(provider: str, system_prompt: str, user_prompt: str, model: str | None = None) -> str:
    """Route a generation request to the chosen provider.

    `model` optionally overrides the provider's default model for this call (used
    e.g. by the meeting dashboard to run heavy transcript jobs on a cheaper, higher
    rate-limit model)."""
    provider = (provider or "openai").lower()
    if provider not in _PROVIDERS:
        raise ValueError(
            f"Unknown provider '{provider}'. Choose one of: {', '.join(_PROVIDERS)}"
        )
    return _PROVIDERS[provider].generate(system_prompt, user_prompt, model)
