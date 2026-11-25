"""lexverify — citation-level verification for generated legal analysis.

The design rule: a language model saying "the quote is in the record" is never
evidence. Tier 0 decides mechanically against hashed source text; an LLM judge
sees only the residue Tier 0 cannot resolve, and its own evidence quote is
re-verified by Tier 0 before anything is accepted.
"""

from .corpus import Corpus, Document, build_corpus
from .spancheck import Match, find_quote
from .claims import Claim, parse_claims
from .verify import STATUSES, ClaimResult, VerificationResult, verify, verify_claim
from .judge import Judge, NullJudge

__all__ = [
    "Corpus",
    "Document",
    "build_corpus",
    "Match",
    "find_quote",
    "Claim",
    "parse_claims",
    "STATUSES",
    "ClaimResult",
    "VerificationResult",
    "verify",
    "verify_claim",
    "Judge",
    "NullJudge",
]

__version__ = "0.1.0"
