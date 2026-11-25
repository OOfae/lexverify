"""Fixed, hash-published source corpus.

Every document carries its own SHA-256; the manifest hashes the sorted document
hashes. A report therefore names the exact bytes it was measured against, and a
stranger can rebuild the corpus and compare the manifest instead of trusting us.

Nothing in here calls a model. This layer is pure, deterministic and testable.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from bisect import bisect_right
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator

# Typographic noise that makes a machine miss a quote a human would call exact.
_CHAR_MAP = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201a": "'",
        "\u201b": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u201e": '"',
        "\u201f": '"',
        "\u2013": "-",
        "\u2014": "-",
        "\u2012": "-",
        "\u2015": "-",
        "\u2212": "-",
        "\u00a0": " ",
        "\u2007": " ",
        "\u202f": " ",
        "\u2009": " ",
        "\u200b": "",
        "\u00ad": "",
        "\ufeff": "",
    }
)

MANIFEST_VERSION = 1


def normalise(text: str) -> tuple[str, list[int]]:
    """Fold ``text`` to a comparison form and keep a map back to the original.

    Whitespace runs collapse to one space, case is folded, typographic quotes
    and dashes are folded to ASCII. The returned offset list has one entry per
    character of the normalised string, holding the index of the character it
    came from, so any match can be reported against the untouched document.
    """
    out: list[str] = []
    offsets: list[int] = []
    prev_space = True
    soft_break = False
    for index, char in enumerate(text):
        if char == "\u00ad":
            # A soft hyphen is a discretionary break, not a character. When the
            # typesetter used it at a line end the word continues onto the next
            # line, so the whitespace that follows must be swallowed instead of
            # becoming a word boundary. Without this, "pri\u00advate" is stored
            # as "pri vate" and an honest quote of "private" fails the check.
            soft_break = True
            continue
        if soft_break and char.isspace():
            continue
        soft_break = False
        char = char.translate(_CHAR_MAP)
        if not char:
            continue
        if char.isspace():
            if prev_space:
                continue
            out.append(" ")
            offsets.append(index)
            prev_space = True
            continue
        folded = unicodedata.normalize("NFKC", char)
        if not folded:
            continue
        if len(folded) > 1:
            folded = folded[0]
        lowered = folded.lower()
        if len(lowered) != 1:
            lowered = folded
        out.append(lowered)
        offsets.append(index)
        prev_space = False

    raw = "".join(out)
    lead = len(raw) - len(raw.lstrip(" "))
    norm = raw.strip(" ")
    return norm, offsets[lead : lead + len(norm)]


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _pdf_pages(path: Path) -> list[str]:
    import pymupdf  # imported lazily so plain-text corpora need no dependency

    with pymupdf.open(path) as opened:
        return [page.get_text("text") for page in opened]


@dataclass
class Document:
    """One source document: page text, normalised text, and offset maps."""

    doc_id: str
    source: str
    sha256: str
    pages: list[str]
    norm: str = ""
    offsets: list[int] = field(default_factory=list)
    page_starts: list[tuple[int, int]] = field(default_factory=list)
    _sentences: list[tuple[int, int]] | None = field(default=None, repr=False)
    _token_sets: list[tuple[int, int, frozenset]] | None = field(default=None, repr=False)

    def prepare(self) -> "Document":
        parts: list[str] = []
        offsets: list[int] = []
        page_starts: list[tuple[int, int]] = []
        total = 0
        for number, page_text in enumerate(self.pages, start=1):
            page_norm, page_offsets = normalise(page_text)
            if not page_norm:
                continue
            if parts:
                parts.append(" ")
                offsets.append(page_offsets[0] if page_offsets else 0)
                total += 1
            page_starts.append((total, number))
            parts.append(page_norm)
            offsets.extend(page_offsets)
            total += len(page_norm)
        self.norm = "".join(parts)
        self.offsets = offsets
        self.page_starts = page_starts
        if len(self.offsets) != len(self.norm):  # invariant guard, fails loudly
            raise ValueError(f"{self.doc_id}: offset map out of step with text")
        return self

    def page_at(self, norm_offset: int) -> int:
        if not self.page_starts:
            return 1
        starts = [start for start, _ in self.page_starts]
        position = bisect_right(starts, norm_offset) - 1
        return self.page_starts[max(position, 0)][1]

    def original_span(self, start: int, end: int) -> tuple[int, int, int, str]:
        """Map a normalised span to (page, page_start, page_end, exact text)."""
        page = self.page_at(start)
        page_text = self.pages[page - 1]
        origin = self.page_starts[max(bisect_right([s for s, _ in self.page_starts], start) - 1, 0)][0]
        page_start = self.offsets[start] if start < len(self.offsets) else len(page_text)
        tail = end - 1
        page_end = (self.offsets[tail] + 1) if tail < len(self.offsets) else len(page_text)
        return page, page_start, page_end, page_text[page_start:page_end]

    def sentences(self) -> list[tuple[int, int]]:
        """Sentence-ish spans of the normalised text, for bounded fuzzy search."""
        if self._sentences is not None:
            return self._sentences
        spans: list[tuple[int, int]] = []
        start = 0
        for match in re.finditer(r"(?<=[.;:])\s+", self.norm):
            end = match.start()
            if end > start:
                spans.append((start, end))
            start = match.end()
        if start < len(self.norm):
            spans.append((start, len(self.norm)))
        self._sentences = spans
        return spans

    def sentence_token_sets(self) -> list[tuple[int, int, frozenset]]:
        """Per-sentence token sets, cached: the cheap prefilter for fuzzy search."""
        if self._token_sets is None:
            self._token_sets = [
                (start, end, frozenset(self.norm[start:end].split()))
                for start, end in self.sentences()
            ]
        return self._token_sets

    def to_json(self) -> dict:
        return {
            "doc_id": self.doc_id,
            "source": self.source,
            "sha256": self.sha256,
            "pages": self.pages,
        }

    @classmethod
    def from_json(cls, data: dict) -> "Document":
        return cls(
            doc_id=data["doc_id"],
            source=data["source"],
            sha256=data["sha256"],
            pages=list(data["pages"]),
        )


class Corpus:
    """A fixed set of documents plus its manifest hash."""

    def __init__(self, documents: Iterable[Document], manifest: dict | None = None):
        self.documents = [doc.prepare() for doc in documents]
        self.manifest = manifest or {}

    def __len__(self) -> int:
        return len(self.documents)

    def __iter__(self) -> Iterator[Document]:
        return iter(self.documents)

    @property
    def manifest_sha256(self) -> str:
        body = "\n".join(f"{doc.doc_id}:{doc.sha256}" for doc in self.documents)
        return hashlib.sha256(body.encode("utf-8")).hexdigest()

    def by_id(self, doc_id: str) -> Document | None:
        for doc in self.documents:
            if doc.doc_id == doc_id:
                return doc
        return None

    def to_json(self) -> dict:
        return {
            "manifest_version": MANIFEST_VERSION,
            "manifest_sha256": self.manifest_sha256,
            "documents": [doc.to_json() for doc in self.documents],
        }

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_json(), indent=2) + "\n", encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "Corpus":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        documents = [Document.from_json(item) for item in data.get("documents", [])]
        corpus = cls(documents, manifest=data)
        recorded = data.get("manifest_sha256")
        if recorded and recorded != corpus.manifest_sha256:
            raise ValueError(
                "corpus manifest does not match its documents: "
                f"recorded {recorded[:12]}…, rebuilt {corpus.manifest_sha256[:12]}…"
            )
        return corpus


def build_corpus(src_dir: Path, extensions: tuple[str, ...] = (".pdf", ".txt")) -> Corpus:
    """Build a corpus from every supported file in ``src_dir`` (sorted)."""
    src = Path(src_dir)
    if not src.exists():
        raise FileNotFoundError(f"no corpus directory at {src}")
    paths = sorted(
        path for path in src.iterdir() if path.suffix.lower() in extensions and path.is_file()
    )
    if not paths:
        raise FileNotFoundError(f"no {extensions} files in {src}")

    documents: list[Document] = []
    for path in paths:
        if path.suffix.lower() == ".pdf":
            pages = _pdf_pages(path)
        else:
            pages = [path.read_text(encoding="utf-8", errors="replace")]
        documents.append(
            Document(
                doc_id=path.stem,
                source=str(path.as_posix()),
                sha256=sha256_file(path),
                pages=pages,
            )
        )
    return Corpus(documents, manifest={"source_dir": str(src.as_posix())})
