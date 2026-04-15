"""LLM provider abstraction — Anthropic and OpenAI-compatible backends."""

import logging
import time
from typing import Protocol

logger = logging.getLogger("minutemaker")


class LLMProvider(Protocol):
    """Interface that all LLM providers must implement."""

    def generate(self, system_prompt: str, user_message: str, config: dict) -> str:
        """Send a prompt to the LLM and return the raw text response."""
        ...


class AnthropicProvider:
    """Provider using the Anthropic Claude API."""

    def generate(self, system_prompt: str, user_message: str, config: dict) -> str:
        import anthropic

        client = anthropic.Anthropic()  # uses ANTHROPIC_API_KEY env var

        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                response = client.messages.create(
                    model=config["model"],
                    max_tokens=config["max_tokens"],
                    temperature=0,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_message}],
                )
                text = response.content[0].text
                tokens_in = response.usage.input_tokens
                tokens_out = response.usage.output_tokens
                logger.info(
                    "Anthropic API call complete (%d input tokens, %d output tokens)",
                    tokens_in,
                    tokens_out,
                )
                return text

            except (anthropic.RateLimitError, anthropic.APIConnectionError) as exc:
                delay = 2**attempt
                if attempt < max_retries:
                    logger.warning(
                        "API error (attempt %d/%d): %s — retrying in %ds",
                        attempt,
                        max_retries,
                        exc,
                        delay,
                    )
                    time.sleep(delay)
                else:
                    raise


class OpenAICompatibleProvider:
    """Provider for any OpenAI-compatible API (Ollama, llama-cpp, vLLM, LM Studio, etc.)."""

    def generate(self, system_prompt: str, user_message: str, config: dict) -> str:
        import openai

        base_url = config.get("base_url", "http://localhost:11434/v1")
        api_key = config.get("api_key", "not-needed")
        client = openai.OpenAI(base_url=base_url, api_key=api_key)

        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                response = client.chat.completions.create(
                    model=config["model"],
                    max_tokens=config["max_tokens"],
                    temperature=0,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message},
                    ],
                )
                text = response.choices[0].message.content
                logger.info("OpenAI-compatible API call complete")
                return text

            except (openai.APIConnectionError, openai.APITimeoutError) as exc:
                delay = 2**attempt
                if attempt < max_retries:
                    logger.warning(
                        "API error (attempt %d/%d): %s — retrying in %ds",
                        attempt,
                        max_retries,
                        exc,
                        delay,
                    )
                    time.sleep(delay)
                else:
                    raise


def get_provider(config: dict) -> LLMProvider:
    """Factory: return the appropriate provider based on config."""
    provider_type = config.get("provider", "anthropic")

    if provider_type == "anthropic":
        return AnthropicProvider()
    elif provider_type == "openai_compatible":
        return OpenAICompatibleProvider()
    else:
        raise ValueError(
            f"Unknown provider: {provider_type!r}. "
            f"Supported: 'anthropic', 'openai_compatible'"
        )
