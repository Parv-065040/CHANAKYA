"""Answer model client: GPT-OSS 120B via Groq (OpenAI-compatible API). Key stays server-side."""
from __future__ import annotations

import logging
import time

import requests

from .config import Settings

log = logging.getLogger("chanakya.llm")

SYSTEM_PROMPT = """You are CHANAKYA, an enterprise knowledge assistant.
Rules:
- Answer ONLY from the numbered evidence supplied. Never use outside knowledge.
- Cite every material claim with its evidence number in square brackets, e.g. [1] or [1][2].
- Never invent sources, numbers or citations. Only cite numbers that exist in the evidence list.
- Use the 'Verified calculations' block for any arithmetic; do not compute yourself. Mark them as calculations.
- Distinguish source facts from calculations. State uncertainty explicitly.
- If the evidence does not contain the answer, reply exactly: I could not find sufficient evidence for this question in the available CHANAKYA knowledge base.
- Be concise for business readers: short answer first, then the calculation if any."""


class LLMUnavailable(RuntimeError):
    """Missing key, quota exhausted, or provider error; caller falls back to offline answer."""


class GroqClient:
    def __init__(self, settings: Settings) -> None:
        self.s = settings

    @property
    def available(self) -> bool:
        return bool(self.s.groq_api_key)

    def complete(self, question: str, context: str, calc_block: str) -> str:
        if not self.available:
            raise LLMUnavailable("GROQ_API_KEY not set")
        user = f"Evidence:\n{context}\n\nVerified calculations:\n{calc_block or 'none'}\n\nQuestion: {question}"
        body = {"model": self.s.groq_model, "temperature": 0.1, "max_tokens": 900,
                "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]}
        headers = {"Authorization": f"Bearer {self.s.groq_api_key}"}
        for attempt in range(2):
            try:
                r = requests.post(f"{self.s.groq_base_url}/chat/completions", json=body, headers=headers, timeout=60)
            except requests.RequestException as exc:
                raise LLMUnavailable(f"network error: {exc.__class__.__name__}") from exc
            if r.status_code == 429:
                raise LLMUnavailable("Groq quota/rate limit reached")
            if r.status_code >= 500 and attempt == 0:
                time.sleep(1.5)
                continue
            if r.status_code != 200:
                raise LLMUnavailable(f"Groq error {r.status_code}")
            try:
                return r.json()["choices"][0]["message"]["content"].strip()
            except (KeyError, IndexError, ValueError) as exc:
                raise LLMUnavailable("malformed Groq response") from exc
        raise LLMUnavailable("Groq unavailable")
