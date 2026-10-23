"""
LLM provider abstraction.

A factory (`get_llm_client`) returns a client instance based on the
LLM_PROVIDER setting in config.py. Each client class implements a common
`query` method, allowing the rest of the application to be model-agnostic.
"""
import abc
import base64
import io
import json

from config import LLM_PROVIDER, ANTHROPIC_API_KEY, OPENAI_API_KEY, GEMINI_API_KEY


def parse_model_json(raw: str):
    """Models sometimes wrap JSON in ```json fences despite instructions —
    strip them before parsing."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw
        # rsplit on ``` and take the first part
        raw = raw.rsplit("```", 1)[0]
    # For Gemini, which might not use markdown fences but can still have trailing text
    raw = raw.strip()
    return json.loads(raw.strip())


def create_vision_messages(prompt_text: str, image_b64: str, provider: str | None = None) -> list:
    """Creates a message payload for a vision model query, adapting the
    format to the configured provider."""
    provider = provider or LLM_PROVIDER
    if provider == "anthropic":
        return [{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": image_b64}},
                {"type": "text", "text": prompt_text}
            ]
        }]
    elif provider == "openai":
        return [{"role": "user", "content": [
            {"type": "input_text", "text": prompt_text},
            {"type": "input_image", "image_url": f"data:image/png;base64,{image_b64}"},
        ]}]
    elif provider == "gemini":
        from PIL import Image

        img_bytes = base64.b64decode(image_b64)
        img = Image.open(io.BytesIO(img_bytes))
        return [prompt_text, img]  # Gemini SDK expects a list of parts
    raise ValueError(f"Vision messages not implemented for provider: {provider}")


class LLM(abc.ABC):
    @abc.abstractmethod
    def query(self, model: str, messages: list, max_tokens: int) -> str:
        """
        Sends a query to the configured LLM and returns the text response.
        """
        pass


class AnthropicLLM(LLM):
    def __init__(self, api_key: str):
        from anthropic import Anthropic

        self.client = Anthropic(api_key=api_key)

    def query(self, model: str, messages: list, max_tokens: int) -> str:
        response = self.client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=messages,
        )
        # Claude's response is a list of content blocks; we extract the text from the first.
        return response.content[0].text.strip()


class OpenAILLM(LLM):
    def __init__(self, api_key: str):
        from openai import OpenAI

        self.client = OpenAI(api_key=api_key)

    def query(self, model: str, messages: list, max_tokens: int) -> str:
        response = self.client.responses.create(
            model=model,
            input=messages,
            max_output_tokens=max_tokens,
        )
        return response.output_text.strip()


class GeminiLLM(LLM):
    def __init__(self, api_key: str):
        from google import genai

        self.client = genai.Client(api_key=api_key)

    @staticmethod
    def _contents(messages: list):
        """Convert common role/content messages to google-genai content objects."""
        if not messages or not all(isinstance(message, dict) for message in messages):
            return messages

        from google.genai import types

        contents = []
        for message in messages:
            role = "model" if message.get("role") == "assistant" else "user"
            raw_content = message.get("content", "")
            raw_parts = raw_content if isinstance(raw_content, list) else [raw_content]
            parts = []
            for part in raw_parts:
                if isinstance(part, str):
                    parts.append(types.Part.from_text(text=part))
                elif isinstance(part, dict) and "text" in part:
                    parts.append(types.Part.from_text(text=part["text"]))
                else:
                    parts.append(part)
            contents.append(types.Content(role=role, parts=parts))
        return contents

    def query(self, model: str, messages: list, max_tokens: int) -> str:
        from google.genai import types

        response = self.client.models.generate_content(
            model=model,
            contents=self._contents(messages),
            config=types.GenerateContentConfig(max_output_tokens=max_tokens),
        )
        return response.text.strip()


_llm_client_instance = None


def get_llm_client() -> LLM:
    """
    Factory function that returns a singleton instance of the configured LLM client.
    """
    global _llm_client_instance
    if _llm_client_instance is None:
        providers = {
            "anthropic": (ANTHROPIC_API_KEY, AnthropicLLM, "ANTHROPIC_API_KEY"),
            "openai": (OPENAI_API_KEY, OpenAILLM, "OPENAI_API_KEY"),
            "gemini": (GEMINI_API_KEY, GeminiLLM, "GEMINI_API_KEY"),
        }
        if LLM_PROVIDER not in providers:
            supported = ", ".join(providers)
            raise ValueError(
                f"Unsupported LLM provider: {LLM_PROVIDER!r}. Choose one of: {supported}."
            )

        api_key, client_class, env_name = providers[LLM_PROVIDER]
        if not api_key or "xxxx" in api_key.lower():
            raise RuntimeError(
                f"LLM_PROVIDER is {LLM_PROVIDER!r} but {env_name} is not set "
                "or still contains the example placeholder."
            )
        _llm_client_instance = client_class(api_key=api_key)
    return _llm_client_instance
