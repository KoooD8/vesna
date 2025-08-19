from __future__ import annotations
import os
from typing import Literal, Optional

try:
    from openai import OpenAI  # type: ignore
except Exception:
    OpenAI = None  # type: ignore

try:
    import anthropic  # type: ignore
except Exception:
    anthropic = None  # type: ignore


Provider = Literal["openai", "anthropic"]


class LLMSummarizer:
    """Minimal LLM summarizer abstraction.

    Usage:
      s = LLMSummarizer(provider="openai", model="gpt-4o-mini")
      text = s.summarize("long text")
    """

    def __init__(self, provider: Provider, model: str, temperature: float = 0.2):
        self.provider = provider
        self.model = model
        self.temperature = temperature
        if provider == "openai":
            if OpenAI is None:
                raise RuntimeError("OpenAI client not installed. Install requirements-extras-llm.txt")
            api_key = os.environ.get("OPENAI_API_KEY")
            if not api_key:
                raise RuntimeError("OPENAI_API_KEY is not set")
            self._client = OpenAI(api_key=api_key)
        elif provider == "anthropic":
            if anthropic is None:
                raise RuntimeError("Anthropic client not installed. Install requirements-extras-llm.txt")
            api_key = os.environ.get("ANTHROPIC_API_KEY")
            if not api_key:
                raise RuntimeError("ANTHROPIC_API_KEY is not set")
            self._client = anthropic.Anthropic(api_key=api_key)
        else:
            raise ValueError(f"Unsupported provider: {provider}")

    def summarize(self, text: str, title: Optional[str] = None) -> str:
        prompt = (
            "Summarize the following content as concise, bullet-point notes with key facts, "
            "sources if present, and a short conclusion. Respond in Markdown.\n\n" + text
        )
        if self.provider == "openai":
            resp = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a helpful research assistant."},
                    {"role": "user", "content": prompt},
                ],
                temperature=self.temperature,
            )
            content = resp.choices[0].message.content or ""
            return content
        elif self.provider == "anthropic":
            msg = self._client.messages.create(
                model=self.model,
                max_tokens=1500,
                temperature=self.temperature,
                messages=[{"role": "user", "content": prompt}],
            )
            # anthropic SDK returns content as a list of blocks; extract text
            parts = []
            for block in getattr(msg, "content", []) or []:
                t = getattr(block, "text", None)
                if t:
                    parts.append(t)
            return "\n".join(parts)
        else:
            raise ValueError("Unsupported provider")

