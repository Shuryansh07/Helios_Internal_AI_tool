"""Google Gemini provider. Works once GEMINI_API_KEY is added to .env."""
import os


def generate(system_prompt: str, user_prompt: str, model: str | None = None) -> str:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set in your .env file.")

    import google.generativeai as genai

    genai.configure(api_key=api_key)
    model_name = model or os.getenv("GEMINI_MODEL", "gemini-2.5-pro")


    model = genai.GenerativeModel(
        model_name=model_name,
        system_instruction=system_prompt,
        generation_config={
            "temperature": 0.3,
            "response_mime_type": "application/json",
        },
    )
    response = model.generate_content(user_prompt)
    return response.text
