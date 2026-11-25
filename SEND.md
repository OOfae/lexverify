# Note to send with the repo

> Jeff — no ask attached to this one.
>
> Everything I read about legal AI last month was measured on *tagging*: recall
> and precision for document review. The product has moved to writing about the
> documents, which is a different risk, and the thing firms say blocks adoption
> is output they cannot trace. So I built the small version of the check I would
> want if I were the one signing the filing.
>
> It does one thing: the model may not state anything I cannot point to. A quote
> is decided by string against a hashed corpus, never by a model. An LLM judge
> only ever sees paraphrases and inferences, it must return a verbatim span, and
> that span is string-checked again before anything is accepted. Anything that
> fails is refused and printed beside the accepted text, not deleted.
>
> On a fixed corpus of eight public Supreme Court opinions: 200 machine-made
> misquotations from two independent generators — mine, and one where Faker
> supplies the party names, case names, statutes, amounts and docket numbers so
> the harness did not pick them — all 200 refused, and none of the 200 real
> sentences used as controls wrongly refused. I would not oversell the catch
> rate: these are synthetic errors, so it proves the machinery, not the method's
> ceiling. The number I actually trust is the false-flag rate, because that one
> can embarrass the design.
>
> The blind spot worth naming before you find it: a quote can be truncated to
> invert its holding and still be verbatim. "Does not preclude a presumption"
> becomes "precludes a presumption" and every word is sourced. String checking
> cannot see that. That residue is what a reader is for, and the report says so.
>
> `build/report.md` shows every verdict with document, page and character
> offsets, and the corpus manifest hash, so any of it can be rerun and checked
> rather than believed.
>
> If it is useful, the obvious next step is running it over a firm's own
> produced set, where the corpus is real and the errors are not mine.
>
> Osatevbose

## Before you send

1. **Run it once yourself and keep the output.** `python examples/make_sample.py
   && python -m lexverify verify --corpus build/corpus.json --input
   examples/sample_analysis.txt --selfcheck 100`. Attach `build/report.md`, not
   just the code — the report is the evidence, the repo is the method.
2. **Do not claim it catches real misquotations at 100%.** Say: 100 synthetic
   cases, 0 false flags on controls, no human-authored test set yet. The moment
   you round that up, a litigator will find the seam.
3. **Keep the limits section.** It is in the report and the README on purpose.
   Removing it is the one edit that would cost you the reader.
