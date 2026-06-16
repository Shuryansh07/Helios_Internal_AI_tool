"""OpenAI provider. This is the one you have a key for today."""
import os
import time


def generate(system_prompt: str, user_prompt: str, model: str | None = None) -> str:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set in your .env file.")

    # Imported lazily so the app still starts if the package isn't installed.
    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    model = model or os.getenv("OPENAI_MODEL", "gpt-4o")

    # Retry transient rate-limit (429) errors with simple backoff.
    last_exc = None
    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model=model,
                temperature=0.3,  # low temperature => sober, realistic, less "wild"
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            return response.choices[0].message.content
        except Exception as exc:  # noqa: BLE001 - normalise across openai versions
            last_exc = exc
            msg = str(exc).lower()
            is_rate = "rate_limit" in msg or "429" in msg or "tokens per min" in msg
            if is_rate and attempt < 2:
                time.sleep(8 * (attempt + 1))  # 8s, 16s
                continue
            raise
    raise last_exc
