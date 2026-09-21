"""
Thin LLM wrapper. Provider is selected with LLM_PROVIDER (gemini or openai) so
the pipeline is not tied to one vendor.
"""
import logging

from app.config import (
    GEMINI_API_KEY,
    LLM_MAX_OUTPUT_TOKENS,
    LLM_MODEL,
    LLM_PROVIDER,
    OPENAI_API_KEY,
)

log = logging.getLogger(__name__)


class LLMNotConfigured(RuntimeError):
    pass


class LLMError(RuntimeError):
    pass


_client = None


def _gemini_client():
    global _client
    if _client is None:
        if not GEMINI_API_KEY:
            raise LLMNotConfigured("GEMINI_API_KEY is not set")
        from google import genai

        _client = genai.Client(api_key=GEMINI_API_KEY)
    return _client


def _openai_client():
    global _client
    if _client is None:
        if not OPENAI_API_KEY:
            raise LLMNotConfigured("OPENAI_API_KEY is not set")
        from openai import OpenAI

        _client = OpenAI(api_key=OPENAI_API_KEY)
    return _client


def is_configured() -> bool:
    if LLM_PROVIDER == "gemini":
        return bool(GEMINI_API_KEY)
    if LLM_PROVIDER == "openai":
        return bool(OPENAI_API_KEY)
    return False


def generate(system_prompt: str, user_prompt: str) -> str:
    """Return the model's text answer, or raise LLMError on failure."""
    try:
        if LLM_PROVIDER == "gemini":
            from google.genai import types

            response = _gemini_client().models.generate_content(
                model=LLM_MODEL,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    max_output_tokens=LLM_MAX_OUTPUT_TOKENS,
                    temperature=0.2,
                ),
            )
            return (response.text or "").strip()

        if LLM_PROVIDER == "openai":
            response = _openai_client().chat.completions.create(
                model=LLM_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=LLM_MAX_OUTPUT_TOKENS,
                temperature=0.2,
            )
            return (response.choices[0].message.content or "").strip()

        raise LLMNotConfigured(f"Unsupported LLM_PROVIDER '{LLM_PROVIDER}'")

    except LLMNotConfigured:
        raise
    except Exception as exc:
        log.exception("LLM call failed")
        raise LLMError(str(exc)) from exc
