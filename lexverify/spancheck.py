"""Tier 0: the deterministic check.

Given a quoted passage, find it in the corpus by string, not by opinion.

* ``exact`` — the normalised quote is a substring of a source document.
* ``fuzzy`` — a close token-level match inside one source sentence.
* ``None``  — no match. A quote nobody wrote is a fabrication, and no model
  should be asked to overrule the text.

The distinction that matters inside the fuzzy tier is *which* words moved. A
typo, a dropped "the", a plural is variance. A negated clause, a changed
number, a swapped party name is a different proposition even at 92% similarity,
and it is refused. That is where misquotation actually lives in legal writing.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field

from .corpus import Corpus, Document, normalise

# Similarity floor for a passage to be worth comparing at all. Similarity never
# accepts a quote on its own: the material-edit check has the final say.
ACCEPT_SIMILARITY = 0.90
MISQUOTE_FLOOR = 0.75

NEGATIONS = {"not", "no", "never", "none", "neither", "nor", "cannot", "without"}

# Words whose insertion or removal rarely changes what a sentence asserts.
FUNCTION_WORDS = set(
    """a an the of and or to in on for that this these those with as by is are was
    were be been being it its at from into than then there here which who whom whose
    also such may might shall will would should could can has have had do does did
    under over upon pursuant while where when if any all each other more most very
    """.split()
)

_SUFFIXES = ("s", "es", "ed", "ing", "ly")

# Sentence punctuation rides along on tokens; it is not an edit. Stripping it
# stops a perfect quote from being reported as changed because it lost a period.
_STRIP = ".,;:!?\"'()[]{}—–-"


def _clean(token: str) -> str:
    return token.strip(_STRIP)


def _same_lemma(left: str, right: str) -> bool:
    if left == right:
        return True
    a, b = left.lower(), right.lower()
    for suffix in _SUFFIXES:
        if a.endswith(suffix) and a[: -len(suffix)] == b:
            return True
        if b.endswith(suffix) and b[: -len(suffix)] == a:
            return True
    return False


def _is_typo(left: str, right: str) -> bool:
    """One misspelled word is a typo; one changed digit or negation is not."""
    if not left or not right:
        return False
    if any(char.isdigit() for char in left + right):
        return False
    if left in NEGATIONS or right in NEGATIONS:
        return False
    if left == right:
        return True
    if abs(len(left) - len(right)) > 2 and min(len(left), len(right)) < 8:
        return False
    return difflib.SequenceMatcher(autojunk=False, a=left, b=right).ratio() >= 0.8


def _is_material(token: str) -> bool:
    lowered = token.lower()
    if lowered in NEGATIONS:
        return True
    if any(char.isdigit() for char in lowered):
        return True
    return lowered not in FUNCTION_WORDS


def tolerance_pairs(quote_tokens: list[str], window_tokens: list[str]) -> list[tuple[int, int, int, int]]:
    """Opcodes in which a replacement counts as the same word."""
    matcher = difflib.SequenceMatcher(autojunk=False)
    matcher.set_seq1(window_tokens)
    matcher.set_seq2(quote_tokens)
    return matcher.get_opcodes()


def material_edits(quote_tokens: list[str], window_tokens: list[str]) -> list[str]:
    """Tokens that changed in a way that can change what the sentence asserts."""
    edited: list[str] = []
    for tag, i1, i2, j1, j2 in tolerance_pairs(quote_tokens, window_tokens):
        if tag == "equal":
            continue
        quote_part = quote_tokens[j1:j2]
        window_part = window_tokens[i1:i2]
        if tag == "replace" and len(quote_part) == len(window_part):
            for left, right in zip(quote_part, window_part):
                left_clean, right_clean = _clean(left), _clean(right)
                if _same_lemma(left_clean, right_clean) or _is_typo(left_clean, right_clean):
                    continue
                if _is_material(left_clean) or _is_material(right_clean):
                    edited.append(f"{left_clean}->{right_clean}")
            continue
        for token in quote_part + window_part:
            cleaned = _clean(token)
            if cleaned and _is_material(cleaned):
                edited.append(cleaned)
    return edited


def similarity(quote_tokens: list[str], window_tokens: list[str]) -> float:
    """Share of the quote present in the window, counting typos as present.

    Counting a typo as present is deliberate: if it counted as absence, every
    misspelling would look like a fabrication and the numbers would be flattering
    nonsense. The material-edit check is what refuses a changed proposition.
    """
    matched = 0
    for tag, i1, i2, j1, j2 in tolerance_pairs(quote_tokens, window_tokens):
        if tag == "equal":
            matched += i2 - i1
            continue
        if tag == "replace" and (i2 - i1) == (j2 - j1):
            for left, right in zip(window_tokens[i1:i2], quote_tokens[j1:j2]):
                left_clean, right_clean = _clean(left), _clean(right)
                if _same_lemma(left_clean, right_clean) or _is_typo(left_clean, right_clean):
                    matched += 1
    longest = max(len(quote_tokens), len(window_tokens))
    return matched / longest if longest else 0.0


@dataclass
class Match:
    tier: str  # "exact" | "fuzzy"
    doc_id: str
    page: int
    page_start: int
    page_end: int
    text: str
    similarity: float
    norm_start: int
    norm_end: int
    changed_tokens: list[str] = field(default_factory=list)

    @property
    def accepted(self) -> bool:
        """Whether the quote may be treated as present in the record."""
        if self.tier == "exact":
            return True
        return self.similarity >= ACCEPT_SIMILARITY and not self.changed_tokens

    def as_dict(self) -> dict:
        return {
            "tier": self.tier,
            "doc_id": self.doc_id,
            "page": self.page,
            "page_start": self.page_start,
            "page_end": self.page_end,
            "text": self.text,
            "similarity": round(self.similarity, 4),
            "changed_tokens": self.changed_tokens,
        }


def _build_match(
    doc: Document,
    start: int,
    end: int,
    tier: str,
    score: float,
    changed: list[str] | None = None,
) -> Match:
    page, page_start, page_end, text = doc.original_span(start, end)
    return Match(
        tier=tier,
        doc_id=doc.doc_id,
        page=page,
        page_start=page_start,
        page_end=page_end,
        text=text,
        similarity=score,
        norm_start=start,
        norm_end=end,
        changed_tokens=changed or [],
    )


def find_quote(corpus: Corpus, quote: str) -> Match | None:
    """Locate ``quote`` in the corpus, exactly first and then fuzzily."""
    normalised, _ = normalise(quote)
    if len(normalised) < 4:
        return None

    for doc in corpus.documents:
        position = doc.norm.find(normalised)
        if position >= 0:
            return _build_match(doc, position, position + len(normalised), "exact", 1.0)

    quote_tokens = normalised.split()
    if len(quote_tokens) < 5:
        return None

    quote_set = set(quote_tokens)
    needed = max(4, int(0.6 * len(quote_tokens)))
    best: tuple[float, Document, int, int] | None = None

    for doc in corpus.documents:
        for start, end, token_set in doc.sentence_token_sets():
            if len(token_set & quote_set) < needed:
                continue
            window_tokens = doc.norm[start:end].split()
            score = similarity(quote_tokens, window_tokens)
            if score >= MISQUOTE_FLOOR and (best is None or score > best[0]):
                best = (score, doc, start, end)

    if best is None:
        return None

    score, doc, start, end = best
    window_tokens = doc.norm[start:end].split()
    changed = material_edits(quote_tokens, window_tokens)
    return _build_match(doc, start, end, "fuzzy", score, changed)


def classify(match: Match | None) -> str:
    """Turn a match into the four outcomes Tier 0 can speak to."""
    if match is None:
        return "not_in_record"
    if match.tier == "exact":
        return "present"
    if match.changed_tokens:
        return "misquote"
    if match.similarity >= ACCEPT_SIMILARITY:
        return "present_with_variance"
    return "misquote"
