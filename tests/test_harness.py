"""Tests for the deterministic core. No network, no model, no fixtures on disk."""

from __future__ import annotations

import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lexverify.claims import parse_claims, split_sentences
from lexverify.corpus import Corpus, Document, normalise
"""Tests for the deterministic core. No network, no model, no fixtures on disk."""

from __future__ import annotations

import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lexverify.claims import parse_claims, split_sentences
from lexverify.corpus import Corpus, Document, normalise
from lexverify.spancheck import classify, find_quote
from lexverify.verify import verify

PAGE_ONE = (
    "The defendant knowingly violated the statute. "
    "The court held that the agreement was void because it lacked consideration. "
    "Section 12 imposes a penalty of 5,000 dollars on any carrier that fails to report."
)
PAGE_TWO = (
    "In U.S. v. Smith, the court reaffirmed that a valid input is not a correct answer. "
    "The dissent would have remanded for further proceedings."
)


def build_corpus() -> Corpus:
    document = Document(
        doc_id="opinion-a",
        source="memory://opinion-a",
        sha256="0" * 64,
        pages=[PAGE_ONE, PAGE_TWO],
    )
    return Corpus([document])


class NormaliseTests(unittest.TestCase):
    def test_offsets_map_back_to_original(self):
        text = "The Court\u2019s    holding \u201cstands\u201d."
        norm, offsets = normalise(text)
        self.assertEqual(len(norm), len(offsets))
        position = norm.find("court's")
        self.assertGreaterEqual(position, 0)
        original = text[offsets[position] : offsets[position + len("court's") - 1] + 1]
        self.assertEqual(original.lower(), "court\u2019s")

    def test_whitespace_collapses(self):
        self.assertEqual(normalise("a   b\n\nc")[0], "a b c")

    def test_soft_hyphen_at_a_line_break_joins_the_word(self):
        # PDF extraction breaks a word as "pri\u00ad\nvate"; a reader quoting the
        # sentence writes "private", and that must not count as an edit.
        self.assertEqual(normalise("a pri\u00ad\nvate individual")[0], "a private individual")
        self.assertEqual(normalise("defni\u00ad tions")[0], "defnitions")


class SpanCheckTests(unittest.TestCase):
    def setUp(self):
        self.corpus = build_corpus()

    def test_exact_match_reports_page_and_offset(self):
        match = find_quote(self.corpus, "the court held that the agreement was void")
        self.assertIsNotNone(match)
        self.assertEqual(match.tier, "exact")
        self.assertEqual(match.page, 1)
        self.assertEqual(PAGE_ONE[match.page_start : match.page_end].lower(),
                         "the court held that the agreement was void")

    def test_page_boundaries_are_tracked(self):
        match = find_quote(self.corpus, "the dissent would have remanded")
        self.assertIsNotNone(match)
        self.assertEqual(match.page, 2)

    def test_fabricated_quote_is_not_found(self):
        self.assertIsNone(find_quote(self.corpus, "the court held that the treaty was void ab initio"))

    def test_inserted_negation_is_material(self):
        match = find_quote(
            self.corpus,
            "the court held that the agreement was not void because it lacked consideration",
        )
        self.assertIsNotNone(match)
        self.assertEqual(match.tier, "fuzzy")
        self.assertTrue(match.changed_tokens)
        self.assertIn("not", match.changed_tokens)
        self.assertFalse(match.accepted)
        self.assertEqual(classify(match), "misquote")

    def test_changed_number_is_material(self):
        match = find_quote(
            self.corpus,
            "section 12 imposes a penalty of 9,000 dollars on any carrier that fails to report.",
        )
        self.assertIsNotNone(match)
        self.assertFalse(match.accepted)

    def test_typo_is_variance_not_misquote(self):
        match = find_quote(
            self.corpus,
            "the court held that the agreemnt was void because it lacked consideration",
        )
        self.assertIsNotNone(match)
        self.assertFalse(match.changed_tokens)
        self.assertTrue(match.accepted)
        self.assertEqual(classify(match), "present_with_variance")


class AttributionTests(unittest.TestCase):
    def setUp(self):
        first = Document(
            doc_id="opinion-a",
            source="memory://a",
            sha256="0" * 64,
            pages=[PAGE_ONE],
        )
        second = Document(
            doc_id="opinion-b",
            source="memory://b",
            sha256="1" * 64,
            pages=[PAGE_TWO],
        )
        self.corpus = Corpus([first, second])

    def test_real_quote_cited_to_the_wrong_case_is_refused(self):
        # The words come from opinion-a; the claim attributes them to Smith,
        # whose name only appears in opinion-b.
        text = 'In U.S. v. Smith, the court held that "the agreement was void because it lacked consideration".'
        result = verify(self.corpus, text)
        self.assertEqual(result.claims[0].status, "refused_misattributed")

    def test_correct_attribution_still_passes(self):
        text = 'The court held that "the agreement was void because it lacked consideration".'
        result = verify(self.corpus, text)
        self.assertEqual(result.claims[0].status, "grounded")


class ClaimParsingTests(unittest.TestCase):
    def test_abbreviations_do_not_split_sentences(self):
        sentences = split_sentences("In U.S. v. Smith, the court ruled. It remanded.")
        self.assertEqual(len(sentences), 2)
        self.assertTrue(sentences[0].startswith("In U.S. v. Smith"))

    def test_quote_and_kind_extraction(self):
        claims = parse_claims('The court said "the agreement was void" in its opinion.')
        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0].kind, "quote")
        self.assertEqual(claims[0].quote, "the agreement was void")

    def test_bullets_are_single_claims(self):
        claims = parse_claims("- First claim here.\n- Second claim here.")
        self.assertEqual(len(claims), 2)

    def test_inference_marker(self):
        claims = parse_claims("Therefore the carrier must report every shipment.")
        self.assertEqual(claims[0].kind, "inference")


class VerifyTests(unittest.TestCase):
    def setUp(self):
        self.corpus = build_corpus()

    def test_grounded_claim_accepted_and_fabrication_refused(self):
        text = (
            'The court held that "the agreement was void because it lacked consideration".\n'
            'The court also said "the statute is unconstitutional in every application".'
        )
        result = verify(self.corpus, text)
        statuses = [item.status for item in result.claims]
        self.assertEqual(statuses[0], "grounded")
        self.assertEqual(statuses[1], "refused_fabricated")
        self.assertEqual(result.metrics()["accepted"], 1)
        self.assertEqual(len(result.refused), 1)

    def test_paraphrase_is_refused_without_a_judge(self):
        result = verify(self.corpus, "The court was plainly hostile to arbitration.")
        self.assertEqual(result.claims[0].status, "refused_unjudged")
        self.assertEqual(result.accepted_text, "")

    def test_accepted_text_contains_only_grounded_claims(self):
        text = (
            'It said "the dissent would have remanded for further proceedings".\n'
            "The remedy is therefore automatic."
        )
        result = verify(self.corpus, text)
        self.assertIn("dissent", result.accepted_text)
        self.assertNotIn("automatic", result.accepted_text)


class FakerGeneratorTests(unittest.TestCase):
    """The independent generator, on a corpus big enough to draw from."""

    def setUp(self):
        sentences = []
        for index in range(30):
            sentences.append(
                f"In matter {index}, the court held that clause {index} was valid because "
                f"the carrier gave notice on May {index + 1}, 2020 under Section {100 + index}."
            )
        pages = [" ".join(sentences[:15]), " ".join(sentences[15:])]
        self.corpus = Corpus(
            [Document(doc_id="big", source="memory://big", sha256="0" * 64, pages=pages)]
        )

    def test_faker_cases_generate_and_are_caught(self):
        from lexverify.fabricate import evaluate
        from lexverify.faker_cases import build_faker_cases

        cases = build_faker_cases(self.corpus, count=10, seed=3)
        fabricated = [case for case in cases if case.label == "fabricated"]
        self.assertGreaterEqual(len(fabricated), 10)
        self.assertTrue(any(case.kind == "case_cite_swap" or case.kind == "money_swap" for case in cases))

        evaluation = evaluate(self.corpus, cases)
        self.assertGreaterEqual(evaluation["catch_rate"], 0.8)
        self.assertLessEqual(evaluation["false_flag_rate"], 0.1)

    def test_faker_generation_is_deterministic(self):
        from lexverify.faker_cases import build_faker_cases

        first = [case.quote for case in build_faker_cases(self.corpus, count=5, seed=9)]
        second = [case.quote for case in build_faker_cases(self.corpus, count=5, seed=9)]
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
from lexverify.spancheck import classify, find_quote
from lexverify.verify import verify

PAGE_ONE = (
    "The defendant knowingly violated the statute. "
    "The court held that the agreement was void because it lacked consideration. "
    "Section 12 imposes a penalty of 5,000 dollars on any carrier that fails to report."
)
PAGE_TWO = (
    "In U.S. v. Smith, the court reaffirmed that a valid input is not a correct answer. "
    "The dissent would have remanded for further proceedings."
)


def build_corpus() -> Corpus:
    document = Document(
        doc_id="opinion-a",
        source="memory://opinion-a",
        sha256="0" * 64,
        pages=[PAGE_ONE, PAGE_TWO],
    )
    return Corpus([document])


class NormaliseTests(unittest.TestCase):
    def test_offsets_map_back_to_original(self):
        text = "The Court\u2019s    holding \u201cstands\u201d."
        norm, offsets = normalise(text)
        self.assertEqual(len(norm), len(offsets))
        position = norm.find("court's")
        self.assertGreaterEqual(position, 0)
        original = text[offsets[position] : offsets[position + len("court's") - 1] + 1]
        self.assertEqual(original.lower(), "court\u2019s")

    def test_whitespace_collapses(self):
        self.assertEqual(normalise("a   b\n\nc")[0], "a b c")


class SpanCheckTests(unittest.TestCase):
    def setUp(self):
        self.corpus = build_corpus()

    def test_exact_match_reports_page_and_offset(self):
        match = find_quote(self.corpus, "the court held that the agreement was void")
        self.assertIsNotNone(match)
        self.assertEqual(match.tier, "exact")
        self.assertEqual(match.page, 1)
        self.assertEqual(PAGE_ONE[match.page_start : match.page_end].lower(),
                         "the court held that the agreement was void")

    def test_page_boundaries_are_tracked(self):
        match = find_quote(self.corpus, "the dissent would have remanded")
        self.assertIsNotNone(match)
        self.assertEqual(match.page, 2)

    def test_fabricated_quote_is_not_found(self):
        self.assertIsNone(find_quote(self.corpus, "the court held that the treaty was void ab initio"))

    def test_inserted_negation_is_material(self):
        match = find_quote(
            self.corpus,
            "the court held that the agreement was not void because it lacked consideration",
        )
        self.assertIsNotNone(match)
        self.assertEqual(match.tier, "fuzzy")
        self.assertTrue(match.changed_tokens)
        self.assertIn("not", match.changed_tokens)
        self.assertFalse(match.accepted)
        self.assertEqual(classify(match), "misquote")

    def test_changed_number_is_material(self):
        match = find_quote(
            self.corpus,
            "section 12 imposes a penalty of 9,000 dollars on any carrier that fails to report.",
        )
        self.assertIsNotNone(match)
        self.assertFalse(match.accepted)

    def test_typo_is_variance_not_misquote(self):
        match = find_quote(
            self.corpus,
            "the court held that the agreemnt was void because it lacked consideration",
        )
        self.assertIsNotNone(match)
        self.assertFalse(match.changed_tokens)
        self.assertTrue(match.accepted)
        self.assertEqual(classify(match), "present_with_variance")


class AttributionTests(unittest.TestCase):
    def setUp(self):
        first = Document(
            doc_id="opinion-a",
            source="memory://a",
            sha256="0" * 64,
            pages=[PAGE_ONE],
        )
        second = Document(
            doc_id="opinion-b",
            source="memory://b",
            sha256="1" * 64,
            pages=[PAGE_TWO],
        )
        self.corpus = Corpus([first, second])

    def test_real_quote_cited_to_the_wrong_case_is_refused(self):
        # The words come from opinion-a; the claim attributes them to Smith,
        # whose name only appears in opinion-b.
        text = 'In U.S. v. Smith, the court held that "the agreement was void because it lacked consideration".'
        result = verify(self.corpus, text)
        self.assertEqual(result.claims[0].status, "refused_misattributed")

    def test_correct_attribution_still_passes(self):
        text = 'The court held that "the agreement was void because it lacked consideration".'
        result = verify(self.corpus, text)
        self.assertEqual(result.claims[0].status, "grounded")


class ClaimParsingTests(unittest.TestCase):
    def test_abbreviations_do_not_split_sentences(self):
        sentences = split_sentences("In U.S. v. Smith, the court ruled. It remanded.")
        self.assertEqual(len(sentences), 2)
        self.assertTrue(sentences[0].startswith("In U.S. v. Smith"))

    def test_quote_and_kind_extraction(self):
        claims = parse_claims('The court said "the agreement was void" in its opinion.')
        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0].kind, "quote")
        self.assertEqual(claims[0].quote, "the agreement was void")

    def test_bullets_are_single_claims(self):
        claims = parse_claims("- First claim here.\n- Second claim here.")
        self.assertEqual(len(claims), 2)

    def test_inference_marker(self):
        claims = parse_claims("Therefore the carrier must report every shipment.")
        self.assertEqual(claims[0].kind, "inference")


class VerifyTests(unittest.TestCase):
    def setUp(self):
        self.corpus = build_corpus()

    def test_grounded_claim_accepted_and_fabrication_refused(self):
        text = (
            'The court held that "the agreement was void because it lacked consideration".\n'
            'The court also said "the statute is unconstitutional in every application".'
        )
        result = verify(self.corpus, text)
        statuses = [item.status for item in result.claims]
        self.assertEqual(statuses[0], "grounded")
        self.assertEqual(statuses[1], "refused_fabricated")
        self.assertEqual(result.metrics()["accepted"], 1)
        self.assertEqual(len(result.refused), 1)

    def test_paraphrase_is_refused_without_a_judge(self):
        result = verify(self.corpus, "The court was plainly hostile to arbitration.")
        self.assertEqual(result.claims[0].status, "refused_unjudged")
        self.assertEqual(result.accepted_text, "")

    def test_accepted_text_contains_only_grounded_claims(self):
        text = (
            'It said "the dissent would have remanded for further proceedings".\n'
            "The remedy is therefore automatic."
        )
        result = verify(self.corpus, text)
        self.assertIn("dissent", result.accepted_text)
        self.assertNotIn("automatic", result.accepted_text)


class FakerGeneratorTests(unittest.TestCase):
    """The independent generator, on a corpus big enough to draw from."""

    def setUp(self):
        sentences = []
        for index in range(30):
            sentences.append(
                f"In matter {index}, the court held that clause {index} was valid because "
                f"the carrier gave notice on May {index + 1}, 2020 under Section {100 + index}."
            )
        pages = [" ".join(sentences[:15]), " ".join(sentences[15:])]
        self.corpus = Corpus(
            [Document(doc_id="big", source="memory://big", sha256="0" * 64, pages=pages)]
        )

    def test_faker_cases_generate_and_are_caught(self):
        from lexverify.fabricate import evaluate
        from lexverify.faker_cases import build_faker_cases

        cases = build_faker_cases(self.corpus, count=10, seed=3)
        fabricated = [case for case in cases if case.label == "fabricated"]
        self.assertGreaterEqual(len(fabricated), 10)
        self.assertTrue(any(case.kind == "case_cite_swap" or case.kind == "money_swap" for case in cases))

        evaluation = evaluate(self.corpus, cases)
        self.assertGreaterEqual(evaluation["catch_rate"], 0.8)
        self.assertLessEqual(evaluation["false_flag_rate"], 0.1)

    def test_faker_generation_is_deterministic(self):
        from lexverify.faker_cases import build_faker_cases

        first = [case.quote for case in build_faker_cases(self.corpus, count=5, seed=9)]
        second = [case.quote for case in build_faker_cases(self.corpus, count=5, seed=9)]
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
