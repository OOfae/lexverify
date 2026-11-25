"""Report rendering: JSON for machines, Markdown for a person deciding to trust it.

Every report names the corpus manifest hash, so the numbers are attached to a
specific set of bytes rather than to a date and a claim.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .corpus import Corpus
from .verify import VerificationResult

_LIMITS = """\
## What this measures

- Whether a quoted passage exists in the hashed corpus, and where (document, page, character offsets).
- Whether a fuzzy match differs in ways that can change meaning: negations, numbers, party names.
- Whether a paraphrase or inference survived a judge **and** the judge's own evidence quote verified.

## What this does not measure

- **Whether the argument is right.** A sentence can be verbatim and still be read wrongly.
- **Whether the corpus is complete.** Absence of a quote proves it is not in *these documents*, not that it does not exist.
- **Whether the judge is right.** The judge is the same class of model as the one being checked; a shared blind spot stays invisible.
- **Scale.** This ran on a fixed, small corpus. It is a demonstration of a method, not a benchmark of a vendor.
"""


def _table(rows: list[list[str]], header: list[str]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join(["---"] * len(header)) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(cell.replace("|", "\\|") for cell in row) + " |")
    return "\n".join(lines)


def markdown_report(
    result: VerificationResult,
    corpus: Corpus,
    source_name: str = "analysis",
    fabrications: list[dict] | None = None,
) -> str:
    metrics = result.metrics()
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    out: list[str] = []
    out.append(f"# Verification report — {source_name}")
    out.append("")
    out.append(f"Generated {stamp} · judge: `{result.judge_name}`")
    out.append("")
    out.append(f"Corpus manifest `{corpus.manifest_sha256}` · {len(corpus)} documents")
    out.append("")

    out.append("## Result")
    out.append("")
    out.append(
        _table(
            [
                ["Claims parsed", str(metrics["claims"])],
                ["Accepted (grounded)", str(metrics["accepted"])],
                ["Refused", str(metrics["refused"])],
                ["Quoted claims decided by Tier 0 alone", f"{metrics['quoted_decided_without_judge']} / {metrics['quoted_claims']}"],
                ["Judge calls", str(metrics["judge_calls"])],
                ["Judge calls avoided", str(metrics["judge_avoided"])],
            ],
            ["Measure", "Value"],
        )
    )
    out.append("")

    status_rows = [
        [status, str(count)]
        for status, count in metrics["by_status"].items()
        if count
    ]
    if status_rows:
        out.append("## Verdicts by status")
        out.append("")
        out.append(_table(status_rows, ["Status", "Claims"]))
        out.append("")

    for run in fabrications or []:
        out.append(
            f"## Deterministic tier against a labeled fabrication set — {run['generator']} generator"
        )
        out.append("")
        out.append(
            _table(
                [
                    ["Fabricated quotations", str(run["fabricated_cases"])],
                    ["Caught", f"{run['fabricated_caught']} ({run['catch_rate'] * 100:.1f}%)"],
                    ["True controls", str(run["control_cases"])],
                    ["True controls wrongly flagged", f"{run['control_cases'] - run['control_accepted']} ({run['false_flag_rate'] * 100:.1f}%)"],
                ],
                ["Measure", "Value"],
            )
        )
        out.append("")
        kind_rows = [
            [kind, str(values["cases"]), str(values["caught"]), f"{values['catch_rate'] * 100:.1f}%"]
            for kind, values in run["by_kind"].items()
        ]
        out.append(_table(kind_rows, ["Edit", "Cases", "Caught", "Catch rate"]))
        out.append("")

    out.append("## Claims")
    out.append("")
    for item in result.claims:
        mark = "ACCEPTED" if item.accepted else "REFUSED"
        out.append(f"**{item.claim.index + 1}. {mark} — `{item.status}`**")
        out.append("")
        out.append(f"> {item.claim.text}")
        out.append("")
        detail: list[str] = []
        if item.match:
            detail.append(
                f"source: `{item.match.doc_id}` p.{item.match.page}, chars {item.match.page_start}-{item.match.page_end}, similarity {item.match.similarity:.3f}"
            )
            detail.append(f"in record: \"{item.match.text[:300]}\"")
        if item.match and item.match.changed_tokens:
            detail.append("changed: " + ", ".join(item.match.changed_tokens[:8]))
        if item.judge:
            detail.append(f"judge: {item.judge.verdict} — {item.judge.rationale}")
        if item.evidence:
            detail.append(f"judge evidence verified at `{item.evidence.doc_id}` p.{item.evidence.page}")
        if item.reason:
            detail.append(f"reason: {item.reason}")
        for line in detail:
            out.append(f"- {line}")
        out.append("")

    if result.refused:
        out.append("## Refused output (not for filing)")
        out.append("")
        for item in result.refused:
            out.append(f"- {item.claim.text}")
        out.append("")

    out.append("## Corpus documents")
    out.append("")
    out.append(
        _table(
            [[doc.doc_id, doc.sha256[:16] + "…", str(len(doc.pages))] for doc in corpus],
            ["Document", "SHA-256", "Pages"],
        )
    )
    out.append("")
    out.append(_LIMITS)
    return "\n".join(out) + "\n"
