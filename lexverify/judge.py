"""Tier 1: the judge, and only for the residue.

Two rules hold this layer in place.

1. The judge never sees a quotation. Quotations are decided by string, above.
   What reaches the judge is a paraphrase or an inference with no quoted span —
   the part Tier 0 is structurally unable to settle.
2. The judge must answer with a verbatim evidence quote, and that quote is sent
   back through Tier 0. If the judge's own evidence does not survive the
   string check, the verdict is void. A judge cannot launder a claim by being
   confident about text that does not exist.

No key means no judge: residue is reported as unjudged, never as supported.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field

DEFAULT_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_MODEL = "llama-3.3-70b-versatile"

_SYSTEM = (
    "You are a verification reader. You are given one claim and passages from "
    "source documents. You decide whether the passages support the claim as "
    "written. You may not use outside knowledge, and you may not assume a fact "
    "because it is generally true. If support is partial, say PARTIAL. If the "
    "passages do not support it, say UNSUPPORTED. Answer only with JSON: "
    '{"verdict": "SUPPORTED"|"PARTIAL"|"UNSUPPORTED", "evidence_quote": "<a '
    'verbatim span copied character for character from one passage, or empty>", '
    '"rationale": "<one sentence>"}'
)


@dataclass
class JudgeVerdict:
    verdict: str  # SUPPORTED | PARTIAL | UNSUPPORTED | ERROR
    evidence_quote: str = ""
    rationale: str = ""
    model: str = ""
    error: str = ""

    def as_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "evidence_quote": self.evidence_quote,
            "rationale": self.rationale,
            "model": self.model,
            "error": self.error,
        }


class NullJudge:
    """The honest no-key judge: it never claims support for anything."""

    available = False
    name = "null"

    def support(self, claim: str, passages: list[dict]) -> JudgeVerdict:
        return JudgeVerdict(verdict="ERROR", rationale="no judge configured", error="no_api_key")


class Judge:
    """OpenAI-compatible chat judge (Groq by default), strict JSON out."""

    available = True
    name = "llm"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        endpoint: str | None = None,
        timeout: int = 45,
    ):
        self.api_key = api_key or os.environ.get("GROQ_API_KEY", "")
        self.model = model or os.environ.get("LEXVERIFY_JUDGE_MODEL", DEFAULT_MODEL)
        self.endpoint = endpoint or os.environ.get("LEXVERIFY_JUDGE_ENDPOINT", DEFAULT_ENDPOINT)
        self.timeout = timeout
        self.calls = 0
        if not self.api_key:
            raise ValueError("Judge needs an API key; use NullJudge when there is none")

    @classmethod
    def maybe(cls) -> "Judge | NullJudge":
        """A real judge when a key is present, the null judge otherwise."""
        if os.environ.get("GROQ_API_KEY") or (
            os.environ.get("LEXVERIFY_JUDGE_ENDPOINT") and os.environ.get("LEXVERIFY_JUDGE_MODEL")
        ):
            try:
                return cls()
            except ValueError:
                return NullJudge()
        return NullJudge()

    def _payload(self, claim: str, passages: list[dict]) -> dict:
        body = "\n\n".join(
            f"[{index + 1}] doc={p['doc_id']} page={p['page']}\n{p['text']}"
            for index, p in enumerate(passages)
        )
        return {
            "model": self.model,
            "temperature": 0,
            "max_tokens": 400,
            "messages": [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": f"CLAIM:\n{claim}\n\nPASSAGES:\n{body}"},
            ],
        }

    def support(self, claim: str, passages: list[dict]) -> JudgeVerdict:
        if not passages:
            return JudgeVerdict(
                verdict="UNSUPPORTED", rationale="no candidate passage retrieved", model=self.model
            )
        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(self._payload(claim, passages)).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        self.calls += 1
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            return JudgeVerdict(verdict="ERROR", error=str(error), model=self.model)

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            return JudgeVerdict(verdict="ERROR", error="malformed response", model=self.model)

        return self._parse(content)

    def _parse(self, content: str) -> JudgeVerdict:
        text = content.strip()
        text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            return JudgeVerdict(verdict="ERROR", error="no json", model=self.model)
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return JudgeVerdict(verdict="ERROR", error="bad json", model=self.model)
        verdict = str(data.get("verdict", "")).upper().strip()
        if verdict not in {"SUPPORTED", "PARTIAL", "UNSUPPORTED"}:
            return JudgeVerdict(verdict="ERROR", error="bad verdict", model=self.model)
        return JudgeVerdict(
            verdict=verdict,
            evidence_quote=str(data.get("evidence_quote", "") or "").strip(),
            rationale=str(data.get("rationale", "") or "").strip()[:400],
            model=self.model,
        )
