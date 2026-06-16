"""Anthropic Claude provider. Works once CLAUDE_API_KEY is added to .env."""
import os


def generate(system_prompt: str, user_prompt: str, model: str | None = None) -> str:
    api_key = os.getenv("CLAUDE_API_KEY")
    if not api_key:
        raise RuntimeError("CLAUDE_API_KEY is not set in your .env file.")

    from anthropic import Anthropic

    client = Anthropic(api_key=api_key)
    model = model or os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

    # Claude returns JSON reliably when we instruct it to and prefill with "{".
    message = client.messages.create(
        model=model,
        max_tokens=4096,
        temperature=0.3,
        system=system_prompt,
        messages=[
            {"role": "user", "content": user_prompt},
            {"role": "assistant", "content": "{"},
        ],
    )
    return "{" + message.content[0].text
