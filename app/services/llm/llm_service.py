import json
import logging
from typing import Any

from anthropic import Anthropic
from openai import OpenAI

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class LLMService:
    """Unified LLM interface supporting OpenAI and Anthropic."""

    def __init__(self) -> None:
        self.provider = settings.llm_provider
        self.model = settings.llm_model
        self._openai: OpenAI | None = None
        self._anthropic: Anthropic | None = None

        if self.provider == "openai" and settings.openai_api_key:
            self._openai = OpenAI(api_key=settings.openai_api_key,
                                  base_url=settings.openai_base_url)
        elif self.provider == "anthropic" and settings.anthropic_api_key:
            self._anthropic = Anthropic(api_key=settings.anthropic_api_key)

    def complete_json(self, system_prompt: str, user_prompt: str, temperature: float = 0.2) -> dict[str, Any]:
        raw = self.complete(system_prompt, user_prompt, temperature, json_mode=True)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(raw[start:end])
            raise

    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.3,
        json_mode: bool = False,
    ) -> str:
        if self.provider == "openai" and self._openai:
            kwargs: dict[str, Any] = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": temperature,
            }
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}
            response = self._openai.chat.completions.create(**kwargs)
            return response.choices[0].message.content or ""

        if self.provider == "anthropic" and self._anthropic:
            response = self._anthropic.messages.create(
                model=self.model,
                max_tokens=4096,
                system=system_prompt + ("\nRespond with valid JSON only." if json_mode else ""),
                messages=[{"role": "user", "content": user_prompt}],
                temperature=temperature,
            )
            return response.content[0].text

        raise RuntimeError(f"LLM provider '{self.provider}' not configured")
