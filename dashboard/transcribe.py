"""
Audio → text transcription for the Live Capture page.

Provider-agnostic so you're not locked in:
  - "huggingface" (default, cheap): HF Inference API running a Whisper model.
  - "openai" (fallback, robust): OpenAI Whisper API.

Auto-selection: if TRANSCRIBE_PROVIDER=huggingface but no HF token is set yet, it
falls back to OpenAI (you already have that key) so the feature works immediately;
add HF_API_TOKEN to switch to the cheaper path with no code change.
"""
import io
import os
import time

import requests

PROVIDER = os.getenv("TRANSCRIBE_PROVIDER", "huggingface").lower()
HF_MODEL = os.getenv("HF_ASR_MODEL", "openai/whisper-large-v3")
OPENAI_ASR_MODEL = os.getenv("OPENAI_ASR_MODEL", "whisper-1")


def _provider() -> str:
    if PROVIDER == "huggingface" and os.getenv("HF_API_TOKEN"):
        return "huggingface"
    if os.getenv("OPENAI_API_KEY"):
        return "openai"
    if PROVIDER == "huggingface":
        return "huggingface"  # will raise a clear error about the missing token
    return PROVIDER


def transcribe(audio_bytes: bytes, filename: str = "audio.webm") -> str:
    prov = _provider()
    if prov == "huggingface":
        return _huggingface(audio_bytes)
    return _openai(audio_bytes, filename)


def _huggingface(audio_bytes: bytes) -> str:
    token = os.getenv("HF_API_TOKEN")
    if not token:
        raise RuntimeError("HF_API_TOKEN is not set in .env (add a free token from "
                           "huggingface.co/settings/tokens, or set TRANSCRIBE_PROVIDER=openai).")
    url = f"https://api-inference.huggingface.co/models/{HF_MODEL}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "audio/webm"}
    # Serverless models cold-start: retry on 503 "model is loading".
    for attempt in range(4):
        r = requests.post(url, headers=headers, data=audio_bytes, timeout=180)
        if r.status_code == 503:
            wait = 12 * (attempt + 1)
            time.sleep(wait)
            continue
        if r.status_code >= 400:
            raise RuntimeError(f"HF transcription failed ({r.status_code}): {r.text[:200]}")
        try:
            j = r.json()
        except Exception:
            return r.text.strip()
        if isinstance(j, dict):
            return (j.get("text") or "").strip()
        if isinstance(j, list) and j:
            return (j[0].get("text") or "").strip()
        return str(j).strip()
    raise RuntimeError("Hugging Face model is still loading after several retries — try again shortly.")


def _openai(audio_bytes: bytes, filename: str) -> str:
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not set.")
    from openai import OpenAI
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    f = io.BytesIO(audio_bytes)
    f.name = filename or "audio.webm"
    r = client.audio.transcriptions.create(model=OPENAI_ASR_MODEL, file=f)
    return (getattr(r, "text", "") or "").strip()


def active_provider() -> dict:
    return {"provider": _provider(), "hf_model": HF_MODEL,
            "hf_token_set": bool(os.getenv("HF_API_TOKEN"))}
