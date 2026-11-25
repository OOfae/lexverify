"""Turn a block of generated analysis into claims the harness can judge.

A claim is one sentence-ish unit. Each carries its quoted span (if any), any
case citation it makes, and a type, because the types are not verified the same
way: a quotation can be checked by string, a paraphrase or an inference cannot.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Abbreviations that end in a period but not a sentence. Without this list the
# splitter turns "U.S. v. Smith" into three claims and the report lies.
_ABBREVIATIONS = (
    "u.s", "v", "no", "nos", "mr", "mrs", "ms", "dr", "prof", "cir", "ct", "sup",
    "supp", "f", "f.2d", "f.3d", "f.4th", "s", "ev", "art", "sec", "ch", "id",
    "cf", "e.g", "i.e", "etc", "inc", "ltd", "co", "corp", "llp", "ex", "rel",
)

_QUOTE_PATTERNS = (
    re.compile(r'"(?P<quote>[^"]{8,1200})"'),
    re.compile(r"\u201c(?P<quote>[^\u201d]{8,1200})\u201d"),
)

# "Party v. Party" and nothing after it: an earlier version swallowed the rest
# of the sentence, which made the attribution check miss the wrong-case error.
_CASE_CITE = re.compile(
    r"((?:[A-Z][A-Za-z'&.\-]*\s+){0,3}v\.?\s+[A-Z][A-Za-z'&.\-]*(?:\s+[A-Z][A-Za-z'&.\-]*){0,3})"
)
_DOCKET = re.compile(r"\bNo\.\s*\d{1,2}-\d{2,6}\b")

_INFERENCE_MARKERS = (
    "therefore", "thus", "this suggests", "this means", "accordingly", "as a result",
    "it follows", "consequently", "that implies", "this implies",
)


@dataclass
class Claim:
    index: int
    text: str
    quote: str | None
    cite: str | None
    docket: str | None
    kind: str  # "quote" | "paraphrase" | "inference"

    def as_dict(self) -> dict:
        return {
            "index": self.index,
            "kind": self.kind,
            "text": self.text,
            "quote": self.quote,
            "cite": self.cite,
            "docket": self.docket,
        }


def _ends_with_abbreviation(chunk: str) -> bool:
    tail = chunk.rstrip()
    if not tail.endswith("."):
        return False
    token = tail[:-1].rsplit(" ", 1)[-1].strip("(),;:").lower()
    return token in _ABBREVIATIONS or len(token) == 1


def split_sentences(paragraph: str) -> list[str]:
    """Split on sentence punctuation, refusing to break known abbreviations."""
    pieces = re.split(r"(?<=[.!?])\s+", paragraph.strip())
    sentences: list[str] = []
    buffer = ""
    for piece in pieces:
        candidate = f"{buffer} {piece}".strip() if buffer else piece
        if _ends_with_abbreviation(candidate):
            buffer = candidate
            continue
        sentences.append(candidate)
        buffer = ""
    if buffer:
        sentences.append(buffer)
    return [sentence.strip() for sentence in sentences if sentence.strip()]


def _extract_quote(sentence: str) -> str | None:
    found: list[str] = []
    for pattern in _QUOTE_PATTERNS:
        found.extend(match.group("quote") for match in pattern.finditer(sentence))
    if not found:
        return None
    return max(found, key=len).strip()


def _extract_cite(sentence: str) -> str | None:
    match = _CASE_CITE.search(sentence)
    if match:
        return match.group(1).strip(" ,.;")
    docket = _DOCKET.search(sentence)
    return docket.group(0) if docket else None


def parse_claims(text: str) -> list[Claim]:
    """Parse analysis text into claims, in reading order.

    Bullet lines (``- ``, ``* ``, ``1. ``) are treated as one claim each, which
    is how most generated case summaries are shaped.
    """
    claims: list[Claim] = []
    index = 0
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        bullets = re.findall(r"^(?:[-*\u2022]|\d{1,2}[.)])\s+(.*)$", line)
        units = bullets if bullets else split_sentences(line)
        for unit in units:
            quote = _extract_quote(unit)
            lowered = unit.lower().lstrip()
            if quote:
                kind = "quote"
            elif any(lowered.startswith(marker) for marker in _INFERENCE_MARKERS):
                kind = "inference"
            else:
                kind = "paraphrase"
            claims.append(
                Claim(
                    index=index,
                    text=unit,
                    quote=quote,
                    cite=_extract_cite(unit),
                    docket=(_DOCKET.search(unit).group(0) if _DOCKET.search(unit) else None),
                    kind=kind,
                )
            )
            index += 1
    return claims
