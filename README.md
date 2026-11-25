# lexverify

Citation-level verification for generated legal analysis.

A language model saying *"the quote is in the record"* is never evidence. This
harness treats that sentence as untrusted, decides it against hashed source text,
and refuses to emit anything it cannot prove — including the sentences a judge
model wrote to support them.

## The problem it points at

Legal AI vendors publish recall and precision for *tagging documents*. The
product surface has since moved to *writing about them*: analysis, summaries,
strategy memos. That is a different risk class. A wrong tag costs review time; a
fabricated quotation in a filing costs sanctions — the Fifth Circuit imposed one
in February 2026 over a brief with 21 fabricated or misrepresented quotations.
Surveys put "output I cannot trace to a source" at the top of the adoption
barrier list, ahead of cost.

Provenance for documents a firm already holds is solved. Provenance for the
sentences the model writes *about* them is not. This is a small, working
demonstration of what that looks like.

## Four rules, enforced in code

1. **Tier 0 first, deterministically.** A quoted passage is matched against the
   corpus by string. Same corpus, same quote, same answer, every run. No model
   participates.
2. **The judge sees only the residue.** A quotation is never sent to an LLM. Only
   a paraphrase or inference with no quoted span reaches the judge — the part
   strings structurally cannot settle.
3. **The judge's own evidence is re-verified.** It must return a verbatim span;
   that span goes back through Tier 0. Evidence that does not verify voids the
   verdict. Confidence cannot launder a quote that does not exist.
4. **Refusal is the default.** Unsupported, partial, unjudged, misquoted,
   fabricated — all refused. Accepted output is assembled only from claims that
   passed, and refused claims are reported beside them rather than deleted.
5. **Attribution is checked separately from the string.** A real quotation
   cited to the wrong case is still a false citation. If the cited authority
   does not appear in the document the quote came from, but does appear in
   another one, the claim is refused as misattributed.

The subtle rule that matters most: a fuzzy match is accepted **only when the
edits are non-material**. A typo, a plural, a dropped "the" is variance. An
inserted "not", a changed number, a swapped party name is a different
proposition at 96% similarity, and it is refused. That is where legal
misquotation actually lives.

## Quickstart

```bash
# optional: the independent generator needs faker, the core does not
python -m pip install faker

# 1. fetch a fixed corpus of public-domain Supreme Court slip opinions
python corpus/fetch_slip_opinions.py 8

# 2. hash and index it
python -m lexverify build-corpus --src corpus/docs --out build/corpus.json

# 3. label 100 synthetic misquotations and score the deterministic tier
python -m lexverify fabricate --corpus build/corpus.json --count 100

# 4. build a demo analysis from real quotes, then verify it
python examples/make_sample.py
python -m lexverify verify --corpus build/corpus.json \
    --input examples/sample_analysis.txt --selfcheck 100

# 5. with a judge for the residue (optional; without it residue is refused as unjudged)
export GROQ_API_KEY=...
python -m lexverify verify --corpus build/corpus.json \
    --input examples/sample_analysis.txt --judge llm --out-md build/report.md
```

Python 3.10+. The deterministic core has no dependencies. PDFs need `pymupdf`;
`pytest` is not required, tests run with `python -m unittest discover -s tests`.

## What the numbers mean

`build/fabrications.json` contains the labeled set and its evaluation:

- **catch rate** — of the crafted misquotations, how many Tier 0 refused. The
  set spans four edits: negated clause, changed figure, swapped party, spliced
  half-sentence.
- **false flag rate** — of untouched control sentences from the same corpus, how
  many were wrongly refused. A catch rate without this number is marketing.

`build/report.md` contains per-claim verdicts with document, page and character
offsets, plus the corpus manifest hash so the run can be reproduced byte for
byte.

### Two generators, on purpose

`fabricate.py` builds errors from the same vocabulary the detector uses.
`faker_cases.py` builds them from Faker: party names, companies, case names,
statute numbers, amounts and docket numbers the harness did not choose. Run both
with `--selfcheck-generator both`; they are reported separately and never
averaged, because averaging two different tests hides which one is weak.

Faker buys independence of *values*, not realism. It is still a machine, and it
still cannot produce the errors a tired associate makes at 2 a.m.

### Why a perfect score here is not the claim

The reference run catches 100 of 100 and flags 0 of 100 controls. That is not
impressive, and it should not be read as one: the fabrication set is generated
by machine against the same definitions the detector uses, so it measures
whether the machinery works, not whether it will catch a misquotation a lawyer
wrote by hand. A real benchmark needs human-authored errors, documents outside
the corpus, and quotes longer than one sentence. Until then the number to trust
is the false-flag rate on controls, because that one can embarrass the design.

## Known blind spots

- **Truncation that flips meaning.** Cut "the court does not preclude a federal
  presumption" down to "the court precludes a federal presumption" by removing a
  clause, and the remaining words are still verbatim, so Tier 0 accepts them. A
  quote can be perfectly sourced and still invert the holding. Nothing in this
  harness reads for sense; that residue needs a reader.
- **Quotes longer than one sentence.** Fuzzy search is bounded to one sentence
  span, so a misquotation across a sentence break falls back to exact matching.
- **Silence.** It can prove a quote is absent from the corpus. It cannot prove
  the corpus is complete.

## What this does not do

- It does not judge whether an argument is right. A sentence can be verbatim and
  still be read wrongly.
- It does not prove a quote is absent from the world, only from this corpus.
- The judge is the same class of model as the one being checked. Shared blind
  spots stay invisible. That is why the judge's evidence is string-checked and
  why it never touches quotations.
- It is not a benchmark of any vendor. The corpus is small and fixed on purpose.

## Layout

```
lexverify/
  corpus.py      normalisation with offset maps, per-document SHA-256, manifest hash
  spancheck.py   Tier 0: exact, then bounded fuzzy with material-edit detection
  claims.py      claim and quotation parsing, citation and docket extraction
  judge.py       Tier 1: OpenAI-compatible judge, strict JSON, NullJudge fallback
  verify.py      pipeline: Tier 0 → residue → judge → evidence re-check → refusal
  fabricate.py   labeled fabrication set and its evaluation
  faker_cases.py independent generator: Faker supplies the wrong words
  report.py      Markdown + JSON reports
  cli.py         build-corpus / fabricate / verify
SEND.md          one-paragraph note to attach when sharing this
corpus/
  fetch_slip_opinions.py   public-domain corpus with provenance hashes
examples/
  make_sample.py           demo analysis built from real corpus quotes
tests/
  test_harness.py          deterministic core, no network
```

## Corpus

US Supreme Court slip opinions, `supremecourt.gov/opinions`, US Government works
in the public domain (17 U.S.C. § 105). URLs, fetch times and SHA-256 of each
file are written to `corpus/provenance.json`. For production, swap in PACER or
CourtListener RECAP filings — the harness only needs PDFs or text files with a
stable hash.
