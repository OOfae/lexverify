"""Build a demonstration analysis from *real* corpus sentences.

Nothing here is invented except the failure cases, which are labeled in the file
itself. The point is that every grounded claim in the sample can be traced to a
page, and the two bad claims are the kind a model actually produces: a negated
quote and a paraphrase with nothing behind it.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lexverify.corpus import Corpus  # noqa: E402

OUTPUT = ROOT / "examples" / "sample_analysis.txt"


def pick(corpus: Corpus, pattern: str, index: int = 0) -> tuple[str, str]:
    regex = re.compile(pattern)
    for doc in corpus.documents:
        for start, end in doc.sentences():
            sentence = doc.norm[start:end].strip()
            words = sentence.split()
            if 12 <= len(words) <= 34 and regex.search(sentence):
                if index <= 0:
                    return doc.doc_id, sentence
                index -= 1
    raise SystemExit(f"no sentence matching {pattern!r} in the corpus")


def negate(sentence: str) -> str:
    for auxiliary in ("is", "are", "was", "were", "shall", "must", "may", "will", "has", "have"):
        match = re.search(rf"\b{auxiliary}\b", sentence)
        if match and not re.search(rf"\b{auxiliary} not\b", sentence):
            return sentence[: match.end()] + " not" + sentence[match.end() :]
    return sentence.replace(" the ", " no ", 1)


def main() -> int:
    corpus = Corpus.load(ROOT / "build" / "corpus.json")
    doc_a, quote_a = pick(corpus, r"\bcourt\b.*\bheld\b")
    doc_b, quote_b = pick(corpus, r"\bstatute\b", index=1)
    doc_c, quote_c = pick(corpus, r"\bjudgment\b")
    doc_d, misquote_base = pick(corpus, r"\bjurisdiction\b")

    text = f"""# Demonstration analysis. Quotes are real; the failures are deliberate and labelled.
# Corpus {corpus.manifest_sha256} over {len(corpus)} documents.

- The Court framed the question as one of statutory interpretation, writing that "{quote_a}" ({doc_a}).
- It treated the text as controlling: "{quote_b}" ({doc_b}).
- The same reasoning appears in the judgment: "{quote_c}" ({doc_c}).
- DELIBERATE FAILURE, negated quotation: "{negate(misquote_base)}" ({doc_d}).
- DELIBERATE FAILURE, unsupported inference: Therefore the rule announced here applies to every filing in every district, without exception.
- DELIBERATE FAILURE, fabricated quotation: "A statute that is silent is a statute that commands nothing at all." ({doc_c}).
- DELIBERATE FAILURE, unquoted figure (no span to check, so it needs a judge): The Court noted that the order affected 9,700 parties in the district.
"""
    OUTPUT.write_text(text, encoding="utf-8")
    print(f"written: {OUTPUT}")
    print(f"  {len(text.splitlines())} lines, quotes drawn from {doc_a}, {doc_b}, {doc_c}, {doc_d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
