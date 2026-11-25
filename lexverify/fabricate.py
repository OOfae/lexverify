"""Labeled fabrication set: the number that makes the harness mean something.

Take real sentences from the hashed corpus and make the four edits that legal
misquotation actually takes — a flipped negation, a changed number, a swapped
party, a spliced half-sentence — then measure what the deterministic tier
catches. Controls are untouched sentences from the same corpus, so a catch
rate is always reported next to a false-flag rate. One without the other is
marketing.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass

from .corpus import Corpus
from .spancheck import find_quote

NUMBER = re.compile(r"\b\d[\d,.]*\b")
CAPITALISED = re.compile(r"\b[A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,})?\b")
AUXILIARIES = ("is", "are", "was", "were", "shall", "must", "may", "will", "has", "have", "does")


@dataclass
class Case:
    case_id: str
    label: str  # "fabricated" | "true"
    kind: str
    quote: str
    doc_id: str

    def as_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "label": self.label,
            "kind": self.kind,
            "quote": self.quote,
            "doc_id": self.doc_id,
        }


def _sentences(corpus: Corpus, low: int = 12, high: int = 34) -> list[tuple[str, str]]:
    """Real sentences in their original case, so a party name is a party name."""
    pool: list[tuple[str, str]] = []
    for doc in corpus.documents:
        for start, end in doc.sentences():
            _, _, _, text = doc.original_span(start, end)
            text = text.strip()
            words = text.split()
            if low <= len(words) <= high and any(c.isalpha() for c in text):
                pool.append((doc.doc_id, text))
    return pool


def _mutate_number(text: str) -> str | None:
    match = NUMBER.search(text)
    if not match:
        return None
    raw = match.group(0)
    digits = re.sub(r"[^\d]", "", raw)
    if not digits:
        return None
    replaced = str(int(digits) + 7)
    return text[: match.start()] + replaced + text[match.end() :]


def _mutate_negation(text: str) -> str | None:
    for auxiliary in AUXILIARIES:
        pattern = re.compile(rf"\b{auxiliary}\b")
        match = pattern.search(text)
        if match:
            if re.search(rf"\b{auxiliary}\s+not\b", text):
                continue
            return text[: match.end()] + " not" + text[match.end() :]
    return None


# Sentence-initial or generic capitals are not party names; swapping "The" for
# "Wilburn Boat" produces a mutation no reader would call a misquotation.
_NOT_A_PARTY = {
    "the", "this", "that", "these", "those", "in", "it", "but", "and", "for",
    "under", "when", "where", "if", "a", "on", "at", "by", "no", "not", "as",
    "however", "because", "although", "there", "then", "thus", "such", "what",
}


def _party_candidate(text: str) -> re.Match | None:
    best = None
    for match in CAPITALISED.finditer(text):
        if match.start() == 0:
            continue
        if match.group(0).lower() in _NOT_A_PARTY:
            continue
        if best is None or len(match.group(0)) > len(best.group(0)):
            best = match
    return best


def _mutate_entity(text: str, donor: str) -> str | None:
    match = _party_candidate(text)
    donor_match = _party_candidate(donor)
    if not match or not donor_match or match.group(0) == donor_match.group(0):
        return None
    return text[: match.start()] + donor_match.group(0) + text[match.end() :]


def _mutate_splice(text: str, donor: str) -> str | None:
    left, right = text.split(), donor.split()
    if len(left) < 8 or len(right) < 8:
        return None
    head = " ".join(left[: int(len(left) * 0.6)])
    tail = " ".join(right[int(len(right) * 0.4) :])
    return f"{head} {tail}"


def build_cases(corpus: Corpus, count: int = 100, seed: int = 7) -> list[Case]:
    rng = random.Random(seed)
    pool = _sentences(corpus)
    if len(pool) < 20:
        raise ValueError("corpus too small to build a fabrication set")
    cases: list[Case] = []
    kinds = ("negation", "number", "entity", "splice")
    produced = 0
    attempts = 0
    # Kinds are drawn by produced-count, not by attempt, so one hard mutation
    # cannot starve the others and flatter the aggregate rate.
    while produced < count and attempts < count * 40:
        attempts += 1
        kind = kinds[produced % len(kinds)]
        mutated = None
        doc_id = ""
        for _ in range(10):
            doc_id, text = pool[rng.randrange(len(pool))]
            donor_doc, donor = pool[rng.randrange(len(pool))]
            if kind == "negation":
                candidate = _mutate_negation(text)
            elif kind == "number":
                candidate = _mutate_number(text)
            elif kind == "entity":
                candidate = _mutate_entity(text, donor)
            else:
                candidate = _mutate_splice(text, donor)
            if candidate and candidate.strip() != text.strip():
                mutated = candidate
                break
        if mutated is None:
            continue
        cases.append(Case(f"f{produced:03d}", "fabricated", kind, mutated.strip(), doc_id))
        control_doc, control = pool[rng.randrange(len(pool))]
        cases.append(Case(f"t{produced:03d}", "true", "verbatim", control.strip(), control_doc))
        produced += 1
    return cases


def evaluate(corpus: Corpus, cases: list[Case]) -> dict:
    """Run the deterministic tier only, and report catch and false-flag rates."""
    fabricated = [case for case in cases if case.label == "fabricated"]
    controls = [case for case in cases if case.label == "true"]

    caught = 0
    missed: list[dict] = []
    by_kind: dict[str, dict[str, int]] = {}
    for case in fabricated:
        match = find_quote(corpus, case.quote)
        present = bool(match and match.accepted)
        bucket = by_kind.setdefault(case.kind, {"cases": 0, "caught": 0})
        bucket["cases"] += 1
        if not present:
            caught += 1
            bucket["caught"] += 1
        else:
            missed.append(
                {
                    "case_id": case.case_id,
                    "kind": case.kind,
                    "quote": case.quote,
                    "matched": match.as_dict() if match else None,
                }
            )

    accepted_controls = 0
    flagged: list[dict] = []
    for case in controls:
        match = find_quote(corpus, case.quote)
        if match and match.accepted:
            accepted_controls += 1
        else:
            flagged.append(
                {
                    "case_id": case.case_id,
                    "quote": case.quote,
                    "matched": match.as_dict() if match else None,
                }
            )

    return {
        "fabricated_cases": len(fabricated),
        "fabricated_caught": caught,
        "catch_rate": round(caught / len(fabricated), 4) if fabricated else 0.0,
        "by_kind": {
            kind: {
                **values,
                "catch_rate": round(values["caught"] / values["cases"], 4) if values["cases"] else 0.0,
            }
            for kind, values in sorted(by_kind.items())
        },
        "control_cases": len(controls),
        "control_accepted": accepted_controls,
        "false_flag_rate": round(1 - accepted_controls / len(controls), 4) if controls else 0.0,
        "missed": missed,
        "false_flags": flagged,
    }
