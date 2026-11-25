"""Command line: build a corpus, make a fabrication set, verify, self-check."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .corpus import Corpus, build_corpus
from .fabricate import Case, build_cases, evaluate
from .faker_cases import build_faker_cases
from .judge import Judge, NullJudge
from .report import markdown_report
from .verify import verify


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def cmd_build(args: argparse.Namespace) -> int:
    corpus = build_corpus(Path(args.src))
    out = Path(args.out)
    corpus.save(out)
    print(f"documents: {len(corpus)}")
    print(f"manifest_sha256: {corpus.manifest_sha256}")
    print(f"written: {out}")
    for doc in corpus:
        print(f"  {doc.doc_id:32s} {doc.sha256[:16]}… pages={len(doc.pages)}")
    return 0


def _make_cases(corpus: Corpus, generator: str, count: int, seed: int) -> list[Case]:
    if generator == "faker":
        return build_faker_cases(corpus, count=count, seed=seed)
    if generator == "both":
        return build_cases(corpus, count=count, seed=seed) + build_faker_cases(
            corpus, count=count, seed=seed
        )
    return build_cases(corpus, count=count, seed=seed)


def _evaluate_generators(corpus: Corpus, generator: str, count: int, seed: int) -> list[dict]:
    runs: list[dict] = []
    if generator in {"synthetic", "both"}:
        cases = build_cases(corpus, count=count, seed=seed)
        runs.append({"generator": "synthetic", **evaluate(corpus, cases)})
    if generator in {"faker", "both"}:
        cases = build_faker_cases(corpus, count=count, seed=seed)
        runs.append({"generator": "faker", **evaluate(corpus, cases)})
    return runs


def cmd_fabricate(args: argparse.Namespace) -> int:
    corpus = Corpus.load(Path(args.corpus))
    cases = _make_cases(corpus, args.generator, args.count, args.seed)
    evaluation = evaluate(corpus, cases)
    payload = {
        "corpus_manifest_sha256": corpus.manifest_sha256,
        "generator": args.generator,
        "cases": [case.as_dict() for case in cases],
        "evaluation": evaluation,
    }
    out = Path(args.out)
    _write(out, json.dumps(payload, indent=2) + "\n")
    print(f"fabricated cases: {evaluation['fabricated_cases']}")
    print(f"caught: {evaluation['fabricated_caught']} ({evaluation['catch_rate'] * 100:.1f}%)")
    print(
        "true controls: "
        f"{evaluation['control_accepted']}/{evaluation['control_cases']} accepted "
        f"(false flag {evaluation['false_flag_rate'] * 100:.1f}%)"
    )
    for kind, values in evaluation["by_kind"].items():
        print(f"  {kind:10s} {values['caught']}/{values['cases']} = {values['catch_rate'] * 100:.1f}%")
    print(f"written: {out}")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    corpus = Corpus.load(Path(args.corpus))
    text = Path(args.input).read_text(encoding="utf-8")

    judge = NullJudge()
    if args.judge == "llm":
        judge = Judge.maybe()
        if judge.available is False:
            print("warning: no GROQ_API_KEY, falling back to the null judge", file=sys.stderr)

    result = verify(corpus, text, judge=judge)

    fabrications = None
    if args.selfcheck:
        fabrications = _evaluate_generators(
            corpus, args.selfcheck_generator, args.selfcheck, args.seed
        )

    payload = {
        "corpus_manifest_sha256": corpus.manifest_sha256,
        "judge": result.judge_name,
        "metrics": result.metrics(),
        "fabrication_selfcheck": fabrications,
        "claims": [item.as_dict() for item in result.claims],
    }
    _write(Path(args.out_json), json.dumps(payload, indent=2) + "\n")
    _write(
        Path(args.out_md),
        markdown_report(result, corpus, source_name=Path(args.input).name, fabrications=fabrications),
    )
    metrics = result.metrics()
    print(f"claims: {metrics['claims']}  accepted: {metrics['accepted']}  refused: {metrics['refused']}")
    print(f"tier0 coverage on quotes: {metrics['tier0_coverage'] * 100:.1f}%  judge calls: {metrics['judge_calls']}")
    for run in fabrications or []:
        print(
            f"fabrication catch [{run['generator']}]: {run['catch_rate'] * 100:.1f}%  "
            f"false flag: {run['false_flag_rate'] * 100:.1f}%"
        )
    print(f"written: {args.out_json}, {args.out_md}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lexverify", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build-corpus", help="hash and index a directory of PDFs or text files")
    build.add_argument("--src", required=True)
    build.add_argument("--out", default="build/corpus.json")
    build.set_defaults(func=cmd_build)

    fabricate = sub.add_parser("fabricate", help="build a labeled fabrication set and score Tier 0 on it")
    fabricate.add_argument("--corpus", default="build/corpus.json")
    fabricate.add_argument("--count", type=int, default=100)
    fabricate.add_argument("--seed", type=int, default=7)
    fabricate.add_argument("--generator", choices=["synthetic", "faker", "both"], default="synthetic")
    fabricate.add_argument("--out", default="build/fabrications.json")
    fabricate.set_defaults(func=cmd_fabricate)

    verify_cmd = sub.add_parser("verify", help="verify a block of analysis against the corpus")
    verify_cmd.add_argument("--corpus", default="build/corpus.json")
    verify_cmd.add_argument("--input", required=True)
    verify_cmd.add_argument("--out-json", default="build/report.json")
    verify_cmd.add_argument("--out-md", default="build/report.md")
    verify_cmd.add_argument("--judge", choices=["none", "llm"], default="none")
    verify_cmd.add_argument("--selfcheck", type=int, default=0, help="also run N labeled fabrications")
    verify_cmd.add_argument(
        "--selfcheck-generator",
        choices=["synthetic", "faker", "both"],
        default="both",
        help="which generator produces the labeled fabrications",
    )
    verify_cmd.add_argument("--seed", type=int, default=7)
    verify_cmd.set_defaults(func=cmd_verify)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
