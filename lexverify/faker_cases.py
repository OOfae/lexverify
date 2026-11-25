"""A second, independent fabrication generator, using Faker for the wrong words.

Why this exists: the first generator builds its errors with the same definitions
the detector uses, which invites the fair objection that the test was written to
be passed. Here the substituted *values* come from a third-party library — party
names, companies, case names, statutes, amounts, docket numbers — so the harness
did not choose them.

What this does not fix: Faker is still synthetic. It makes the vocabulary
independent of the detector; it does not make the errors human. A human-authored
set remains the missing benchmark, and the README says so.
"""

from __future__ import annotations

import random
import re

from .corpus import Corpus
from .fabricate import Case, _party_candidate, _sentences

_NUMBER = re.compile(r"\b\d[\d,]*(?:\.\d+)?\b")
_YEAR = re.compile(r"\b(?:18|19|20)\d{2}\b")
_CASE = re.compile(r"\b([A-Z][A-Za-z'-]+)\s+v\.\s+([A-Z][A-Za-z'-]+)")
_STATUTE = re.compile(r"(§+\s*)(\d+(?:\.\d+)*[a-z]?)")
_SECTION = re.compile(r"\bSection\s+(\d+)")

KINDS = ("party_swap", "money_swap", "year_swap", "docket_inject", "case_cite_swap", "statute_swap")


def _apply(kind: str, text: str, fake) -> str | None:
    if kind == "party_swap":
        match = _party_candidate(text)
        if not match:
            return None
        replacement = fake.company().replace(",", "") if len(match.group(0)) > 9 else fake.last_name().title()
        if replacement.lower() == match.group(0).lower():
            return None
        return text[: match.start()] + replacement + text[match.end() :]

    if kind == "money_swap":
        match = _NUMBER.search(text)
        if not match:
            return None
        original = match.group(0)
        if "." in original or "," not in original:
            replacement = f"{fake.random_int(10, 999)}"
        else:
            replacement = f"{fake.random_int(1, 99)},{fake.random_int(100, 999)}"
        if replacement == original:
            return None
        return text[: match.start()] + replacement + text[match.end() :]

    if kind == "year_swap":
        match = _YEAR.search(text)
        if not match:
            return None
        replacement = str(fake.random_int(1950, 2024))
        if replacement == match.group(0):
            return None
        return text[: match.start()] + replacement + text[match.end() :]

    if kind == "docket_inject":
        docket = f"No. {fake.random_int(10, 24)}-{fake.random_int(1000, 9999)}"
        return f"{text.rstrip()} See {docket}."

    if kind == "case_cite_swap":
        match = _CASE.search(text)
        if not match:
            return None
        replacement = fake.last_name().title()
        if replacement == match.group(2):
            return None
        return text[: match.start(2)] + replacement + text[match.end(2) :]

    if kind == "statute_swap":
        match = _STATUTE.search(text) or _SECTION.search(text)
        if not match:
            return None
        digits = fake.random_int(100, 9999)
        if _STATUTE.search(text):
            return text[: match.start(2)] + str(digits) + text[match.end(2) :]
        return text[: match.start(1)] + str(digits) + text[match.end(1) :]

    return None


def build_faker_cases(corpus: Corpus, count: int = 100, seed: int = 11) -> list[Case]:
    from faker import Faker

    fake = Faker()
    fake.seed_instance(seed)
    rng = random.Random(seed)
    pool = _sentences(corpus)
    if len(pool) < 20:
        raise ValueError("corpus too small to build a fabrication set")

    cases: list[Case] = []
    produced = 0
    attempts = 0
    # Balance matters: an unbalanced set is mostly the easiest mutation, and the
    # catch rate then measures that one edit instead of the method.
    while produced < count and attempts < count * 60:
        attempts += 1
        kind = KINDS[produced % len(KINDS)]
        mutated = None
        doc_id = ""
        for _ in range(10):
            doc_id, text = pool[rng.randrange(len(pool))]
            candidate = _apply(kind, text, fake)
            if candidate and candidate.strip() != text.strip():
                mutated = candidate
                break
        if mutated is None:
            for alternative in KINDS:
                if alternative == kind:
                    continue
                doc_id, text = pool[rng.randrange(len(pool))]
                candidate = _apply(alternative, text, fake)
                if candidate and candidate.strip() != text.strip():
                    mutated, kind = candidate, alternative
                    break
        if mutated is None:
            continue
        cases.append(Case(f"k{produced:03d}", "fabricated", kind, mutated.strip(), doc_id))
        control_doc, control = pool[rng.randrange(len(pool))]
        cases.append(Case(f"c{produced:03d}", "true", "verbatim", control.strip(), control_doc))
        produced += 1
    return cases
