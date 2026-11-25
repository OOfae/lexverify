"""The pipeline: claim in, verdict out, ungrounded sentence refused.

Order matters and is fixed:

1. A claim with a quotation is decided by Tier 0. The judge is not called.
2. A claim with no quotation is retrieved against, then judged, then the
   judge's evidence quote is re-verified by Tier 0.
3. Anything not positively accepted is refused. Refusal is the default; nothing
   is accepted because a model sounded sure.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .claims import Claim, parse_claims
from .corpus import Corpus, normalise
from .judge import JudgeVerdict, NullJudge
from .spancheck import ACCEPT_SIMILARITY, Match, find_quote

STATUSES = {
    "grounded": "quotation found verbatim in the record",
    "grounded_variance": "quotation found with non-material variance (typo, inflection)",
    "grounded_judge": "paraphrase or inference judged supported, judge evidence re-verified",
    "refused_fabricated": "quotation not found anywhere in the corpus",
    "refused_misquote": "quotation resembles the record but materially changed",
    "refused_unsupported": "paraphrase judged unsupported by the cited record",
    "refused_partial": "paraphrase only partly supported by the cited record",
    "refused_judge_evidence_failed": "judge claimed support but its evidence quote did not verify",
    "refused_unjudged": "no judge configured; residue cannot be accepted",
    "refused_misattributed": "quotation is real but sits in a different document than the one cited",
}

ACCEPTED = {"grounded", "grounded_variance", "grounded_judge"}

_STOP = set(
    """the a an of and or to in on for that this with as by is are was were be been it
    its at from not no than then there here which who whom also such may might shall
    will would should could can has have had do does did under over upon""".split()
)


@dataclass
class ClaimResult:
    claim: Claim
    status: str
    match: Match | None = None
    judge: JudgeVerdict | None = None
    evidence: Match | None = None
    reason: str = ""

    @property
    def accepted(self) -> bool:
        return self.status in ACCEPTED

    def as_dict(self) -> dict:
        return {
            "claim": self.claim.as_dict(),
            "status": self.status,
            "accepted": self.accepted,
            "reason": self.reason,
            "source": self.match.as_dict() if self.match else None,
            "judge": self.judge.as_dict() if self.judge else None,
            "judge_evidence": self.evidence.as_dict() if self.evidence else None,
        }


@dataclass
class VerificationResult:
    claims: list[ClaimResult] = field(default_factory=list)
    judge_name: str = "null"
    judge_calls: int = 0

    @property
    def accepted_text(self) -> str:
        return "\n".join(item.claim.text for item in self.claims if item.accepted)

    @property
    def refused(self) -> list[ClaimResult]:
        return [item for item in self.claims if not item.accepted]

    def metrics(self) -> dict:
        counts = {status: 0 for status in STATUSES}
        for item in self.claims:
            counts[item.status] = counts.get(item.status, 0) + 1
        quoted = [item for item in self.claims if item.claim.quote]
        decided_by_tier0 = [
            item for item in self.claims if item.claim.quote and item.status in {
                "grounded", "grounded_variance", "refused_fabricated", "refused_misquote"
            }
        ]
        total = len(self.claims)
        accepted = sum(1 for item in self.claims if item.accepted)
        return {
            "claims": total,
            "accepted": accepted,
            "refused": total - accepted,
            "accepted_rate": round(accepted / total, 4) if total else 0.0,
            "quoted_claims": len(quoted),
            "quoted_decided_without_judge": len(decided_by_tier0),
            "tier0_coverage": round(len(decided_by_tier0) / len(quoted), 4) if quoted else 0.0,
            "judge_calls": self.judge_calls,
            "judge_avoided": len(decided_by_tier0),
            "by_status": counts,
        }


def _tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", normalise(text)[0]) if t not in _STOP]


def retrieve_passages(corpus: Corpus, claim: Claim, limit: int = 3) -> list[dict]:
    """Lexical retrieval, preferring the document the claim actually cites."""
    needles: list[str] = []
    for label in (claim.cite, claim.docket):
        if label:
            needle, _ = normalise(label)
            if len(needle) > 4:
                needles.append(needle)

    keys = set(_tokens(claim.text))
    if not keys:
        return []

    scored: list[tuple[float, object, int, int]] = []
    for doc in corpus.documents:
        cite_bonus = 4.0 if any(needle in doc.norm for needle in needles) else 0.0
        for start, end in doc.sentences():
            span_tokens = set(_tokens(doc.norm[start:end]))
            if not span_tokens:
                continue
            overlap = len(span_tokens & keys)
            if overlap < 3:
                continue
            score = overlap / (1 + len(span_tokens) / 40) + cite_bonus
            scored.append((score, doc, start, end))

    scored.sort(key=lambda item: -item[0])
    passages: list[dict] = []
    for score, doc, start, end in scored:
        page, _, _, text = doc.original_span(start, end)
        passages.append({"doc_id": doc.doc_id, "page": page, "text": text})
        if len(passages) >= limit:
            break
    return passages


def attribution_conflict(corpus: Corpus, claim: Claim, match: Match) -> Corpus | None:
    """A real quote cited to the wrong case is still a false citation.

    The string check cannot see this on its own: the words exist, so Tier 0 is
    happy. Attribution is checked separately — the cited case or docket must
    appear in the document the quote actually came from.
    """
    fillers = ("in ", "see ", "cf ", "accord ", "but ", "and ", "compare ")
    labels = []
    for label in (claim.cite, claim.docket):
        if not label:
            continue
        needle, _ = normalise(label)
        changed = True
        while changed:
            changed = False
            for filler in fillers:
                if needle.startswith(filler):
                    needle = needle[len(filler) :]
                    changed = True
        if len(needle) > 4:
            labels.append((label, needle))
    if not labels:
        return None

    source = corpus.by_id(match.doc_id)
    if source is not None and any(needle in source.norm for _, needle in labels):
        return None

    for label, needle in labels:
        for doc in corpus.documents:
            if doc.doc_id != match.doc_id and needle in doc.norm:
                return doc
    return None


def verify_claim(corpus: Corpus, claim: Claim, judge) -> ClaimResult:
    if claim.quote:
        match = find_quote(corpus, claim.quote)
        if match is None:
            return ClaimResult(
                claim,
                "refused_fabricated",
                reason="the quoted words appear nowhere in the hashed corpus",
            )
        elsewhere = attribution_conflict(corpus, claim, match)
        if elsewhere is not None:
            return ClaimResult(
                claim,
                "refused_misattributed",
                match=match,
                reason=f"the cited authority appears in {elsewhere.doc_id}, not {match.doc_id}",
            )

        if match.tier == "exact":
            return ClaimResult(claim, "grounded", match=match, reason="verbatim match")
        if match.changed_tokens:
            return ClaimResult(
                claim,
                "refused_misquote",
                match=match,
                reason="material change: " + ", ".join(match.changed_tokens[:6]),
            )
        if match.similarity >= ACCEPT_SIMILARITY:
            return ClaimResult(
                claim,
                "grounded_variance",
                match=match,
                reason=f"non-material variance, similarity {match.similarity:.3f}",
            )
        return ClaimResult(
            claim,
            "refused_misquote",
            match=match,
            reason=f"similarity {match.similarity:.3f} below acceptance",
        )

    if isinstance(judge, NullJudge) or not getattr(judge, "available", False):
        return ClaimResult(claim, "refused_unjudged", reason=STATUSES["refused_unjudged"])

    passages = retrieve_passages(corpus, claim)
    verdict = judge.support(claim.text, passages)
    if verdict.verdict == "ERROR":
        return ClaimResult(claim, "refused_unjudged", judge=verdict, reason=verdict.error)
    if verdict.verdict == "UNSUPPORTED":
        return ClaimResult(claim, "refused_unsupported", judge=verdict, reason=verdict.rationale)
    if verdict.verdict == "PARTIAL":
        return ClaimResult(claim, "refused_partial", judge=verdict, reason=verdict.rationale)

    evidence = find_quote(corpus, verdict.evidence_quote) if verdict.evidence_quote else None
    if evidence is None or not evidence.accepted:
        return ClaimResult(
            claim,
            "refused_judge_evidence_failed",
            judge=verdict,
            reason="judge's evidence quote did not verify against the corpus",
        )
    return ClaimResult(
        claim, "grounded_judge", judge=verdict, evidence=evidence, reason=verdict.rationale
    )


def verify(corpus: Corpus, text: str, judge=None) -> VerificationResult:
    judge = judge if judge is not None else NullJudge()
    result = VerificationResult(judge_name=getattr(judge, "name", "null"))
    for claim in parse_claims(text):
        result.claims.append(verify_claim(corpus, claim, judge))
    result.judge_calls = getattr(judge, "calls", 0)
    return result
